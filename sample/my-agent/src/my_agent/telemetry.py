"""Agent-side timing for the ``perf`` graph: two histograms and one JSON logger.

Why this file exists (module 10): the Agent Server measures queue wait and whole-run execution for
you, but it has **no metric** for two things that sit inside execution time and often dominate it:

* how long the graph factory took to build the graph for this run, and
* how long each chat-model call took (the first one of a run is what a user feels as "thinking").

``agent_graph_factory_duration_ms`` and ``agent_model_call_duration_ms`` fill that gap.

Why ``prometheus_client`` and not OpenTelemetry: the server keeps its own OpenTelemetry
``MeterProvider`` private, so ``opentelemetry.metrics.get_meter()`` from agent code returns a no-op
meter. But ``GET /metrics`` on both tiers is ``prometheus_client.generate_latest()`` over the
process-global default ``REGISTRY``, so any histogram registered here is scraped right next to the
server's ``lg_api_*`` families, with no extra port or exporter. Set
``PROMETHEUS_DISABLE_CREATED_SERIES=true`` on the server to drop the ``*_created`` companion series.

Logging goes through ``structlog``, which the server configures for JSON when ``LOG_JSON=true``:
keyword arguments become top-level fields, and the worker binds the run context (``run_id``,
``thread_id``, ``assistant_id``, ``graph_id``) before it calls the factory, so lines logged from here
can be joined to the server's own per-run record with ``jq``.

Both packages ship in the ``langchain/langgraph-api`` image; they are declared in ``pyproject.toml``
so the imports are explicit and version-bounded.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage
from prometheus_client import Histogram

log = structlog.stdlib.get_logger("my_agent")

GRAPH_FACTORY_DURATION_MS = Histogram(
    "agent_graph_factory_duration_ms",
    "Wall time of the graph factory per call, milliseconds. access_context=threads.create_run is a "
    "queue worker about to execute a run; assistants.read, threads.read and threads.update are "
    "API-tier schema and state reads.",
    ["graph_id", "access_context"],
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 1500, 2000, 3000, 5000),
)

MODEL_CALL_DURATION_MS = Histogram(
    "agent_model_call_duration_ms",
    "Wall time of each chat-model call inside a run, milliseconds, including the client's own "
    'retries. first="true" is the first model turn of the run.',
    ["first"],
    buckets=(100, 250, 500, 1000, 2000, 3000, 5000, 10000, 20000, 60000),
)


def _is_first_turn(request: ModelRequest) -> bool:
    """True when the model is called right after the user's message, before any tool call of this run."""
    msgs = request.messages
    return bool(msgs) and isinstance(msgs[-1], HumanMessage)


class TimedModelCall(AgentMiddleware):
    """``create_agent`` middleware that records every model call in ``agent_model_call_duration_ms``."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        label = "true" if _is_first_turn(request) else "false"
        t0 = time.perf_counter()
        try:
            return handler(request)
        finally:
            MODEL_CALL_DURATION_MS.labels(first=label).observe((time.perf_counter() - t0) * 1000)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        label = "true" if _is_first_turn(request) else "false"
        t0 = time.perf_counter()
        try:
            return await handler(request)
        finally:
            MODEL_CALL_DURATION_MS.labels(first=label).observe((time.perf_counter() - t0) * 1000)
