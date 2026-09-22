# LangChain Agent Server: an end-to-end guide for self-hosted teams

This guide takes a team that has never seen the LangChain **Agent Server** from an empty folder to
a production deployment on their own Kubernetes cluster. It is written for a team that runs
**self-hosted LangSmith**, and it presents exactly two ways to run the server:

1. **Standalone Agent Server**: you run the server containers yourself with the
   `langgraph-cloud` Helm chart, your own PostgreSQL and Redis, and your existing container
   pipeline. No control plane. Optional tracing to your LangSmith.
2. **LangSmith Deployments**: your self-hosted LangSmith instance's control plane provisions and
   manages the same server containers in your cluster from an image you built.

LangGraph is the packaging format the server understands, not a limit on what you can deploy:
Deep Agents built with `create_deep_agent`, agents from other frameworks, and plain Python all
ship the same way. Both paths deploy the **same image**, built from the **same `langgraph.json`**. Modules 00 to 06
are identical for both; modules 07 and 08 branch; 09 and 10 apply to both again.

## How to read this guide

| If you are… | Read | You can skim |
| --- | --- | --- |
| A developer building or porting an agent | 00, QS, 01, 02 or 03, 04, 05 | 06 (the "What to focus on" section only), 10 (the graph factory section) |
| A platform or infra engineer deploying it | 00, QS, 01, 04, 06, 07 or 08, 09, 10 | 02, 03, 05 |
| A reviewer deciding between the two paths | 00, 06, the comparison at the end of 08 | everything else |

Every module follows the same shape: *Why this matters*, the concept, a hands-on section with
commands and captured output, a checkpoint you can verify, gotchas, and references to the
LangChain documentation and the Helm chart source.

## Modules

| # | Module | What you will be able to do afterwards |
| --- | --- | --- |
| 00 | [Orientation](docs/00-orientation.md) | Explain what the Agent Server is (including that Deep Agents deploy on it), name the two deployment paths, and list what each requires. |
| QS | [Quickstart](docs/00-quickstart.md) | Go end to end in one sitting: a Deep Agent, `langgraph.json`, `.env`, the dev server, the image, and a split API plus worker stack on Docker Compose. |
| 01 | [Core concepts](docs/01-concepts.md) | Use the vocabulary: graphs, assistants, threads, runs, crons, checkpoints, store, task queue. |
| 02 | [Start a new project](docs/02-new-project.md) | Scaffold a project with uv and the LangGraph CLI, run it locally, call it. Builds `sample/my-agent`. |
| 03 | [Morph an existing project](docs/03-existing-project.md) | Wrap existing code, other agent frameworks, or an existing FastAPI service into an Agent Server app. |
| 04 | [`langgraph.json` deep dive](docs/04-langgraph-json.md) | Read and write every key; know which keys change the image and which change runtime behavior. |
| 05 | [The API surface](docs/05-api-surface.md) | Drive assistants, threads, runs, streams, crons and the store with curl and the Python and JS SDKs. |
| 06 | [Runtime and tuning](docs/06-runtime-and-tuning.md) | Explain API servers versus queue workers, how the split is wired, and which knobs to turn when. |
| 07 | [Standalone deploy with the Helm chart](docs/07-standalone-helm-deploy.md) | Build in your own pipeline, install the chart, run single-host and split modes, go to production. |
| 08 | [Deploy through self-hosted LangSmith Deployments](docs/08-langsmith-deployments-self-hosted.md) | Enable the control plane, deploy the same image from the UI or API, manage revisions, and decide how each deployment gets its Postgres and Redis (in-cluster defaults or managed cloud services). |
| 09 | [Operations](docs/09-operations.md) | Monitor, upgrade, troubleshoot, and run the pre-production checklist. |
| 10 | [Performance deep dive](docs/10-performance-deep-dive.md) | Turn on the run-lifecycle metrics and JSON logs on both tiers, scrape them, read one request's queue wait, graph build and execution time from a dashboard and from the logs, and know which knob each stage points to. Captured live on Docker Compose, with the Kubernetes equivalents. |
| A | [Glossary and links](docs/appendix-glossary-and-links.md) | Look up any term or source cited in the guide. |

## The sample project

Everything in the guide is exercised against one small application in [`sample/`](sample/):

| Path | Purpose |
| --- | --- |
| `sample/quickstart-agent/` | The Deep Agent built in the quickstart: one agent file, `langgraph.json`, `.env.example`, `.dockerignore`. |
| `sample/my-agent/` | A uv project with three graphs: `echo` (deterministic, no model key needed), `agent` (a tool-calling agent built with `create_agent`) and `perf` (a factory-built agent that times its own graph build and model calls, module 10). |
| `sample/my-agent/langgraph.json` | Tells the server which graphs to serve and how to build the image. |
| `sample/clients/` | Python SDK and JS SDK clients used in module 05. |
| `sample/Dockerfile` | Generated by `langgraph dockerfile`; what your pipeline builds. |
| `sample/docker-compose.yml` | Local pre-flight of the built image with PostgreSQL and Redis (single container). |
| `sample/docker-compose.split.yml` | Same, with a separate, scalable worker service: the chart's split mode reproduced locally. |
| `sample/docker-compose.observability.yml` | Overlay for the split stack: Prometheus scraping both tiers, Grafana with the request-lifecycle dashboard provisioned, and the two variables that turn the run-lifecycle metrics on (module 10). |
| `sample/observability/` | The Prometheus scrape config, Grafana provisioning and the dashboard JSON the overlay mounts. The same dashboard works on Kubernetes. |
| `sample/loadgen.py` | Load generator for module 10: chat, IO-bound and CPU-bound scenarios, plus the slow-factory knob. |
| `sample/helm/values-dev.yaml` | Smallest install: bundled PostgreSQL and Redis, single-host mode. |
| `sample/helm/values-split.yaml` | Adds dedicated queue workers and a pre-created Kubernetes Secret. |
| `sample/helm/values-prod.yaml` | External data stores, ingress with TLS, autoscaling, disruption budgets. |
| `sample/helm/values-metrics.yaml`, `podmonitor.yaml`, `prometheusrule.yaml` | Module 10 on Kubernetes: the metrics variables on both tiers, a PodMonitor for both tiers (the queue has no Service), and the first five alerts. |
| `sample/pipeline/*.sh` | Plain shell `build`, `push`, `deploy`, `smoke` steps for any CI system, plus `provision-datastores` and `deploy-control-plane` for the LangSmith Deployments path with managed Postgres and Redis. |

Quick start for the sample:

```bash
cd sample/my-agent
uv sync
cp .env.example .env          # fill in keys later; the echo graph needs none
uv run pytest
uv run langgraph dev          # http://127.0.0.1:2024, docs at /docs
```

## Prerequisites

| Tool | Why | Version used while writing |
| --- | --- | --- |
| Python 3.11+ and `uv` | Project and dependency management | uv 0.9.18, Python 3.12 |
| LangGraph CLI (`langgraph-cli[inmem]`) | Scaffold, run locally, generate the Dockerfile | 0.4.18 (0.4.31 latest on PyPI) |
| Docker | Build the image, run the compose pre-flight | 29.1 |
| `kubectl` and Helm 3 | Deploy the chart | kubectl 1.35, Helm 3.17 |
| A Kubernetes cluster | `kind` was used to validate the guide | kind 0.32 |
| A LangSmith API key **or** an Agent Server license key | The Postgres-backed server refuses to start without one (module 07 shows the exact message) | |
| Prometheus and Grafana (module 10 only; pulled by the Compose overlay) | Scrape and chart the server's metrics | `prom/prometheus:v3.14.0`, `grafana/grafana:13.2.2` |

The server image used throughout is `langchain/langgraph-api:3.12-wolfi`, which shipped
`langgraph-api` 0.14.1 and LangGraph 1.2.11 at the time of writing. The Helm chart is
`langchain/langgraph-cloud` 0.3.4.

## How this guide was validated

Commands and output marked as *captured* were run while writing: the dev server, the SDK clients,
the image build, the compose pre-flight, and a `kind` cluster install of the chart in single-host
and split API/queue modes. The kind install was done twice on purpose: once without any key, to
show the exact "License verification failed" behavior, and once with a LangSmith API key (the
server's development "lite mode"), which completed end to end with the smoke test, SDK traffic,
and log and metric evidence that runs execute on queue pods only. Module 08 is based on the
LangChain documentation, since no self-hosted LangSmith control plane was available. Module 10
was captured on the Compose split stack with the Prometheus and Grafana overlay (the screenshots
in `docs/img/` come from that stack) and, for its Kubernetes section, on a split-mode install of
chart 0.3.4 scraped through the Prometheus Operator.

## Sources

Every module ends with a references list. The primary sources are the
[LangChain documentation](https://docs.langchain.com/langsmith/agent-server) (Agent Server,
LangGraph CLI, self-hosted deployment, environment variables, scaling) and the
[`langgraph-cloud` Helm chart](https://github.com/langchain-ai/helm/tree/main/charts/langgraph-cloud)
(README, `values.yaml`, templates). The appendix consolidates them.
