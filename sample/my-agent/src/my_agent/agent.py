"""A real tool-calling agent built with ``create_agent``.

``create_agent`` returns a compiled LangGraph graph. Here it is wrapped in a *factory function*
instead of being built at import time, for two reasons the guide calls out:

1. The server imports every graph in ``langgraph.json`` at startup. If ``create_agent`` ran at
   import time it would construct the model client immediately, and a missing provider key would
   stop the whole server from starting (including the ``echo`` graph).
2. A factory receives the run ``config``, so the model can be chosen per assistant
   (``config["configurable"]["model"]``) without a rebuild. That is the documented reason to
   prefer a factory over a compiled graph; use a compiled graph when you do not need this.

The server injects the checkpointer and store at runtime; do not pass them here.
"""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig


def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    return f"It is always sunny in {city}."


def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def make_agent(config: RunnableConfig):
    """Build the agent for one run. Called by the server on every invocation."""
    configurable = config.get("configurable", {})
    model = configurable.get("model") or os.environ.get("MODEL", "openai:gpt-4o-mini")
    return create_agent(
        model=model,
        tools=[get_weather, add],
        system_prompt="You are a concise assistant. Use tools when they help.",
    )
