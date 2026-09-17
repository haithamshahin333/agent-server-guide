"""A minimal Deep Agent.

``create_deep_agent`` returns a compiled LangGraph graph with planning, a virtual filesystem and
subagent delegation built in. Because it is a compiled graph, the Agent Server serves it exactly
like any hand-written graph: register it in ``langgraph.json`` and the server does the rest.

The model comes from the ``MODEL`` environment variable in ``provider:model`` form so the same
image can point at OpenAI, Anthropic, Google or a gateway without a rebuild. The provider's API key
(``OPENAI_API_KEY`` and so on) must be present when the module is imported, because the server
imports every graph at start-up and the model client is created right here.
"""

from __future__ import annotations

import os

from deepagents import create_deep_agent

# A tiny local tool so the quickstart needs no search provider. Replace it with your own tools,
# or with a provider's built-in web search as the Deep Agents quickstart shows.
_FACTS = {
    "agent server": "The Agent Server is LangChain's runtime that serves graphs over a REST API with persistence and a task queue.",
    "queue worker": "A queue worker is the container role that executes runs; API containers only serve HTTP.",
    "deep agents": "Deep Agents add planning, a virtual filesystem and subagents on top of a LangChain agent.",
}


def lookup_fact(topic: str) -> str:
    """Look up a short fact about a topic in the local knowledge base."""
    return _FACTS.get(topic.lower(), f"No fact stored for '{topic}'. Known topics: {', '.join(_FACTS)}.")


INSTRUCTIONS = """You are a concise technical assistant for a platform team.
Use the lookup_fact tool before answering questions about the Agent Server, queue workers or Deep Agents.
Plan multi-step work with your todo list, and keep answers to a few sentences."""

agent = create_deep_agent(
    model=os.environ.get("MODEL", "openai:gpt-4o-mini"),
    tools=[lookup_fact],
    system_prompt=INSTRUCTIONS,
)
