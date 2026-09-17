# my-agent (sample)

The sample application deployed throughout the guide. See `../../docs/02-new-project.md`.

- `src/my_agent/echo.py`  deterministic graph, no model key needed (used for smoke tests)
- `src/my_agent/agent.py` tool-calling agent built with `create_agent` (needs a model key)
- `langgraph.json`        tells the Agent Server which graphs to serve and how to build the image

```bash
uv sync
cp .env.example .env
uv run pytest
uv run langgraph dev
```
