"""The ``perf`` graph: a tool-calling agent built by a **graph factory** that measures itself.

Module 10 uses this graph to show where a request's seconds go. It is deliberately small: three
tools whose only purpose is to make queue-worker behaviour visible, plus per-run knobs that let you
reproduce a slow graph factory on purpose.

The graph factory contract, as the server applies it
----------------------------------------------------
``langgraph.json`` points at ``make_perf_agent`` instead of a compiled graph, so the server treats
it as a factory. At start-up it inspects the **type annotations** to decide what to pass: nothing,
``config: RunnableConfig``, or ``config`` plus ``runtime: ServerRuntime`` (``langgraph_sdk.runtime``).
Then it calls the factory on **every** ``get_graph()``, and it memoizes nothing:

* once per run, on the queue worker that executes it
  (``runtime.access_context == "threads.create_run"``, ``runtime.execution_runtime`` is set);
* for every schema or state read on the API tier
  (``assistants.read``, ``threads.read``, ``threads.update``), with ``execution_runtime`` unset.

Three consequences shape this file:

1. **Anything config-independent is built once, at module scope**: the tool objects, the constants,
   the system prompt. Only the model client and the agent object are built per call. Credentials,
   HTTP clients and connection pools belong up here too; a client created inside the factory means
   a new connection pool and TLS handshake per run.
2. **The factory is ``async def``.** A synchronous factory body runs inline on the worker's event
   loop and blocks every other run on that worker while it executes.
3. **Same topology in every context.** Invalid or missing knobs fall back to defaults instead of
   changing the node set, because the API tier's schema reads must describe the graph the worker
   will actually run.

Per-run knobs come from ``config["configurable"]`` (set by the caller on ``runs.create`` /
``runs.wait``, or stored on an assistant). Everything there is caller-supplied, so each knob is
validated and clamped: ``model`` (``provider:model`` string, pattern-checked), ``tools`` (subset of
the three tool names; anything else means all three) and ``factory_delay_ms`` (0 to 5000, applied
only while executing a run, so schema reads stay cheap). ``factory_delay_ms`` exists to show what a
factory doing per-run work looks like on the dashboard and in the logs.

The factory records ``agent_graph_factory_duration_ms`` and logs ``graph_factory_built`` (see
``telemetry.py``). The server itself only logs: a warning when a graph load exceeds 100 ms and an
error above 250 ms.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import socket
import time
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph_sdk.runtime import ServerRuntime

from my_agent.telemetry import GRAPH_FACTORY_DURATION_MS, TimedModelCall, log

MAX_WAIT_SECONDS = 60
MAX_FIB_N = 34  # naive fib(34) is a few seconds of pure Python: enough to show a blocked loop, not enough to trip probes
FACTORY_DELAY_MAX_MS = 5000
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")  # provider:model, e.g. openai:gpt-4o-mini
_DEFAULT_MODEL = os.environ.get("MODEL", "openai:gpt-4o-mini")


# ── Built once per process (config-independent) ──────────────────────────────────────────────────────
@tool
async def wait_for(seconds: int) -> str:
    """Wait for a number of seconds without using CPU (simulates a slow external API call).

    Use this when the user asks to wait, sleep, pause, or simulate a slow tool.

    Args:
        seconds: How long to wait, 0 to 60. Larger values are clamped to 60.
    """
    n = max(0, min(int(seconds), MAX_WAIT_SECONDS))
    await asyncio.sleep(n)
    return f"Waited {n} seconds on {socket.gethostname()}."


def _fib(n: int) -> int:
    return n if n < 2 else _fib(n - 1) + _fib(n - 2)


@tool
def crunch_numbers(n: int) -> str:
    """Compute the n-th Fibonacci number with a deliberately slow, CPU-bound algorithm.

    Use this when the user asks to compute Fibonacci numbers, "burn CPU", or stress the worker.

    Args:
        n: Which Fibonacci number to compute, 0 to 34. Larger values are clamped to 34.
    """
    k = max(0, min(int(n), MAX_FIB_N))
    started = time.perf_counter()
    value = _fib(k)
    return f"fib({k}) = {value}, computed in {time.perf_counter() - started:.2f}s on {socket.gethostname()}."


@tool
def worker_id() -> str:
    """Return the current UTC time and the name of the worker (container or pod) handling this run.

    Use this when the user asks what time it is or which server, worker or pod is answering.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return f"{now} on worker {socket.gethostname()}"


TOOLS = {"wait_for": wait_for, "crunch_numbers": crunch_numbers, "worker_id": worker_id}

SYSTEM_PROMPT = (
    "You are a small demo assistant running on a self-hosted Agent Server. Use wait_for when asked to "
    "wait, sleep or simulate a slow call; use crunch_numbers when asked for Fibonacci numbers or to burn "
    "CPU; use worker_id when asked for the time or which worker is answering. Otherwise answer briefly."
)


# ── Per-run knobs, validated and clamped ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Knobs:
    model: str
    tools: tuple[str, ...]
    factory_delay_ms: int


def _clamp_int(value: object, lo: int, hi: int, default: int) -> int:
    try:
        x = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return min(hi, max(lo, x))


def _tool_subset(value: object) -> tuple[str, ...]:
    names = value.split(",") if isinstance(value, str) else value if isinstance(value, (list, tuple)) else []
    picked = tuple(n.strip() for n in names if isinstance(n, str) and n.strip() in TOOLS)
    # Empty or invalid → all tools, so the topology (model node + tools node) never changes.
    return picked or tuple(TOOLS)


def _knobs(config: RunnableConfig) -> Knobs:
    c = config.get("configurable") or {}
    model = str(c.get("model") or _DEFAULT_MODEL)
    if not _MODEL_RE.match(model):
        model = _DEFAULT_MODEL
    return Knobs(
        model=model,
        tools=_tool_subset(c.get("tools")),
        factory_delay_ms=_clamp_int(c.get("factory_delay_ms"), 0, FACTORY_DELAY_MAX_MS, 0),
    )


# ── The factory ──────────────────────────────────────────────────────────────────────────────────────
async def make_perf_agent(config: RunnableConfig, runtime: ServerRuntime):
    """Build the ``perf`` agent for one call. The server binds both arguments by type annotation."""
    t0 = time.perf_counter()
    knobs = _knobs(config)
    access_context = str(getattr(runtime, "access_context", None) or "unknown")
    executing = getattr(runtime, "execution_runtime", None) is not None

    if executing and knobs.factory_delay_ms:
        # Demo knob: pretend the factory does slow per-run setup (loading tools, connecting to MCP
        # servers, fetching prompts). Awaited, so other runs on this worker keep going; and only while
        # executing, so the API tier's schema reads stay fast.
        await asyncio.sleep(knobs.factory_delay_ms / 1000)

    graph = create_agent(
        # Provider credentials come from the environment (OPENAI_API_KEY, OPENAI_BASE_URL, ...); they are
        # never logged or used as metric labels. max_retries lets the client back off on 429s instead of
        # failing the run; watch lg_api_run_failed_after_retry_counter_total if that is exhausted.
        model=init_chat_model(knobs.model, max_retries=6),
        tools=[TOOLS[name] for name in knobs.tools],
        system_prompt=SYSTEM_PROMPT,
        middleware=[TimedModelCall()],
        name="perf",
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000
    c = config.get("configurable") or {}
    graph_id = str(getattr(runtime, "graph_id", None) or c.get("graph_id") or "perf")
    GRAPH_FACTORY_DURATION_MS.labels(graph_id=graph_id, access_context=access_context).observe(elapsed_ms)
    log.info(
        "graph_factory_built",
        duration_ms=round(elapsed_ms, 1),
        access_context=access_context,
        executing=executing,
        graph_id=graph_id,
        run_id=str(c.get("run_id") or ""),
        thread_id=str(c.get("thread_id") or ""),
        model=knobs.model,
        tools=list(knobs.tools),
        factory_delay_ms=knobs.factory_delay_ms,
    )
    return graph
