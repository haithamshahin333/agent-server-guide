#!/usr/bin/env python3
"""Load generator for module 10: create N runs against an Agent Server and report latency percentiles.

Run it from the sample folder with the project's environment (langgraph-sdk is a dependency of my-agent):

  cd sample
  uv run --project my-agent python loadgen.py --runs 5 --concurrency 5
  uv run --project my-agent python loadgen.py --scenario io --seconds 15 --runs 30 --concurrency 30
  uv run --project my-agent python loadgen.py --runs 5 --concurrency 5 --configurable factory_delay_ms=1500
  uv run --project my-agent python loadgen.py --scenario cpu --n 32 --runs 4 --concurrency 4

Scenarios (all against the ``perf`` assistant unless --assistant says otherwise)
  chat  one short model turn that calls worker_id (default)
  io    the agent calls wait_for(SECONDS): IO-bound, holds a worker slot without using CPU
  cpu   the agent calls crunch_numbers(N): CPU-bound, blocks the worker's event loop

Graph-factory knobs (config.configurable, read by src/my_agent/perf.py:make_perf_agent on every run)
  --configurable factory_delay_ms=1500        # slow factory: build time shows up on the dashboard
  --configurable model=openai:gpt-4o-mini     # provider:model
  --configurable tools=worker_id,wait_for     # comma lists become JSON arrays
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

from langgraph_sdk import get_client

PROMPTS = {
    "chat": "Which worker is answering, and what time is it? One sentence.",
    "io": "Use your wait_for tool to wait {seconds} seconds, then reply with exactly what the tool returned.",
    "cpu": "Use your crunch_numbers tool with n={n} and reply with exactly what the tool returned.",
}


def parse_configurable(items: list[str]) -> dict:
    """KEY=VALUE pairs → dict; values parse as JSON when possible, else comma lists, else strings."""
    out: dict = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not key or not sep:
            raise SystemExit(f"--configurable expects KEY=VALUE, got {item!r}")
        try:
            out[key] = json.loads(raw)
        except ValueError:
            out[key] = raw.split(",") if "," in raw else raw
    return out


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8124", help="Agent Server base URL (the split Compose stack)")
    ap.add_argument("--assistant", default="perf")
    ap.add_argument("--scenario", choices=sorted(PROMPTS), default="chat")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--seconds", type=int, default=10, help="io scenario: seconds to wait per run")
    ap.add_argument("--n", type=int, default=30, help="cpu scenario: Fibonacci index (clamped to 34 server-side)")
    ap.add_argument("--background", action="store_true", help="create runs and exit without waiting for results")
    ap.add_argument("--stateless", action="store_true", help="do not create threads (thread_id=None)")
    ap.add_argument("--configurable", action="append", default=[], metavar="KEY=VALUE",
                    help="graph-factory knob passed as config.configurable (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    configurable = parse_configurable(args.configurable)
    run_kwargs = {"config": {"configurable": configurable}} if configurable else {}

    client = get_client(url=args.url)
    prompt = PROMPTS[args.scenario].format(seconds=args.seconds, n=args.n)
    payload = {"messages": [{"role": "user", "content": prompt}]}
    sem = asyncio.Semaphore(max(1, args.concurrency))
    latencies: list[float] = []
    errors: list[str] = []
    threads: list[str] = []

    async def one(i: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            try:
                thread_id = None
                if not args.stateless:
                    thread_id = (await client.threads.create())["thread_id"]
                    threads.append(thread_id)
                if args.background:
                    run = await client.runs.create(thread_id, args.assistant, input=payload, **run_kwargs)
                    if args.verbose:
                        print(f"  run {i}: created {run['run_id']} status={run['status']}")
                else:
                    result = await client.runs.wait(thread_id, args.assistant, input=payload, **run_kwargs)
                    last = result["messages"][-1]["content"] if isinstance(result, dict) and result.get("messages") else result
                    if args.verbose:
                        print(f"  run {i}: {time.perf_counter() - t0:6.2f}s  thread={thread_id}  {str(last)[:90]!r}")
            except Exception as exc:  # noqa: BLE001 - report every failure kind
                errors.append(f"run {i}: {type(exc).__name__}: {exc}")
                if args.verbose:
                    print(f"  run {i}: ERROR {exc}", file=sys.stderr)
            finally:
                latencies.append(time.perf_counter() - t0)

    wall0 = time.perf_counter()
    knobs = f", configurable={json.dumps(configurable)}" if configurable else ""
    print(f"{args.scenario}: {args.runs} runs, concurrency {args.concurrency}, "
          f"{'background' if args.background else 'wait'} → {args.url} assistant={args.assistant}{knobs}")
    await asyncio.gather(*(one(i) for i in range(args.runs)))
    wall = time.perf_counter() - wall0

    ok = args.runs - len(errors)
    print(f"done in {wall:.1f}s: {ok}/{args.runs} ok, {len(errors)} failed, {ok / wall if wall else 0:.2f} runs/s")
    if latencies and not args.background:
        print(f"latency  p50 {pct(latencies, 50):.2f}s  p95 {pct(latencies, 95):.2f}s  max {max(latencies):.2f}s")
    for e in errors[:10]:
        print("  " + e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
