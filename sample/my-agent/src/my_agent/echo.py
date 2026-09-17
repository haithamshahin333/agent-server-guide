"""A deterministic, LLM-free graph.

Why it exists: every deployment module in the guide needs something to run that does not
require a model-provider key. This graph takes a chat-style ``messages`` list, so it works with
the same clients, Studio and UI hooks as a real agent, but it never calls a model.

It also shows the two ways the server passes configuration into a graph:

* ``context`` (the modern, typed way; sent as ``context`` on a run or stored on an assistant)
* ``config["configurable"]`` (the older way; still widely used)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime


class State(TypedDict):
    # add_messages is a reducer: new messages are appended, not overwritten.
    messages: Annotated[list[AnyMessage], add_messages]


@dataclass
class Context:
    """Static per-run / per-assistant settings. Populated from ``context`` on the API."""

    prefix: str = "echo"
    shout: bool = False


def respond(state: State, runtime: Runtime[Context]) -> State:
    last = state["messages"][-1]
    text = last.content if isinstance(last.content, str) else str(last.content)
    ctx = runtime.context or Context()
    reply = f"{ctx.prefix}: {text}"
    if ctx.shout:
        reply = reply.upper()
    return {"messages": [AIMessage(content=reply)]}


graph = (
    StateGraph(State, context_schema=Context)
    .add_node("respond", respond)
    .add_edge(START, "respond")
    .add_edge("respond", END)
    .compile()
)
