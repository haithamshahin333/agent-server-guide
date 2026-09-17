"""Minimal Python SDK client. Works against `langgraph dev` (no auth) or a deployment.

Usage:
  uv run --with langgraph-sdk python python_client.py [BASE_URL]
Set LANGGRAPH_API_KEY (or pass api_key=) when the server enforces auth.
"""

import os
import sys

from langgraph_sdk import get_sync_client

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:2024"
client = get_sync_client(url=url, api_key=os.environ.get("LANGGRAPH_API_KEY"))

# 1. Health: every server exposes /ok and /info
print("info:", {k: client.http.get("/info")[k] for k in ("version",)})

# 2. A thread keeps state across runs (short-term memory)
thread = client.threads.create(metadata={"user": "demo"})
print("thread:", thread["thread_id"])

# 3. Stream a run on the thread. stream_mode controls what you get back.
for chunk in client.runs.stream(
    thread["thread_id"],
    "echo",  # graph id from langgraph.json, or an assistant id
    input={"messages": [{"role": "user", "content": "hello from the python sdk"}]},
    stream_mode=["updates"],
):
    print("event:", chunk.event, "data:", chunk.data)

# 4. Second turn on the same thread; the reducer appends to messages
final = client.runs.wait(
    thread["thread_id"],
    "echo",
    input={"messages": [{"role": "user", "content": "second turn"}]},
    context={"prefix": "bot", "shout": True},
)
print("messages in thread:", len(final["messages"]))
print("last reply:", final["messages"][-1]["content"])

# 5. Stateless run: no thread, nothing persisted after completion
out = client.runs.wait(None, "echo", input={"messages": [{"role": "user", "content": "one-off"}]})
print("stateless reply:", out["messages"][-1]["content"])
