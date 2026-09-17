# Appendix: glossary and consolidated links

## Glossary

Terms are listed alphabetically within each group. The module where a term is first explained is given in brackets.

### Objects the server manages

| Term | Meaning |
| --- | --- |
| **Assistant** [01] | A graph plus a saved configuration (context or configurable values, name, metadata). The server creates one default assistant per graph at startup; you can create more over the same graph and version them. Passing a graph ID as `assistant_id` selects the default assistant. |
| **Assistant version** [01] | An immutable snapshot of an assistant's configuration. Patching an assistant creates a new version; any version can be promoted back to latest. |
| **Checkpoint** [01] | A saved snapshot of a thread's graph state at one step of a run. Checkpoints make runs resumable and give threads a history. Stored in PostgreSQL by default, MongoDB optionally. |
| **Cron** [01, 05] | A stored run request plus a schedule. Each tick creates a run on a fixed thread or a new thread. Schedules are UTC unless a timezone is given. |
| **Graph** [01] | Your agent logic as a compiled LangGraph graph, or a factory function that returns one. Registered under a graph ID in `langgraph.json`. Node code may use any framework. |
| **Graph ID** [01, 04] | The key in the `graphs` map of `langgraph.json`, for example `echo` or `agent`. Also the name of the default assistant. |
| **Run** [01] | One execution of an assistant, with or without a thread. Consumed by waiting, streaming, or in the background. |
| **Stateless run** [01, 05] | A run with no thread. Nothing is persisted after it completes. |
| **Store** [01, 04] | Long-term key-value memory organised in namespaces, shared across threads. Optional semantic search index and item TTL are configured in `langgraph.json`. |
| **Thread** [01] | A durable conversation: accumulated state plus checkpoint history. At most one run executes on a thread at a time. Threads carry searchable metadata and can be copied, rewound, and pruned. |

### Configuration and code concepts

| Term | Meaning |
| --- | --- |
| **Deep Agents** [00, 03, 06] | Agents built with `create_deep_agent` from the `deepagents` package. They compile to a LangGraph graph, so they deploy on the Agent Server unchanged; their asynchronous subagents run as separate runs and occupy worker slots. |
| **Managed Deep Agents** [00] | LangChain's hosted runtime for deep agents (private preview at the time of writing). A LangChain-hosted product, not one of the two self-hosted paths in this guide. |
| **`api_version`** [04] | `langgraph.json` key that pins the semantic version of the Agent Server used for builds. |
| **Base image** [04, 07] | The LangChain image your code is installed on top of: `langchain/langgraph-api:<python>-<distro>` by default (the sample uses `3.12-wolfi`). Pin an exact one with `base_image`. |
| **Compiled graph** [01] | A graph exported as an already-compiled object. Loaded once per container and reused; the recommended registration style. |
| **Context** [01] | Typed, per-run or per-assistant settings declared with `context_schema` and read from `runtime.context` in nodes. Sent as `"context"` on the API. |
| **Configurable** [01] | The older settings channel: values under `config["configurable"]`, sent as `"config": {"configurable": {...}}` on the API. Also what a factory function receives. |
| **`dockerfile_lines`** [03, 04] | Extra Dockerfile instructions appended after the base image, for system packages and similar. |
| **Durability mode** [01, 06] | How often a run writes checkpoints: `async` (default, after each step, asynchronously), `sync`, or `exit` (final state only). Set per run. |
| **Factory graph (factory function)** [01, 03] | A function `make_graph(config)` that builds and returns a graph. Called on every invocation, so keep it light; use only for per-run customisation such as model selection. |
| **`http` block** [03, 04] | `langgraph.json` section for mounting a custom Starlette/FastAPI app, CORS, configurable and logging headers, middleware order, and `disable_*` route flags. |
| **`image_distro`** [04, 07] | Linux distribution of the base image: `debian` (default), `wolfi` (recommended, smaller), `bookworm`, `bullseye`. |
| **`langgraph.json`** [02, 04] | The one configuration file the CLI and server read: dependencies, graphs, env, auth, http, store, checkpointer, image settings. |
| **LangGraph CLI** [02] | The `langgraph` command: `new`, `dev`, `up`, `build`, `dockerfile`, `deploy`. Requires Python 3.11 or newer. |
| **Multitask strategy** [01, 05] | What a thread does when a second run arrives while one is executing: `reject`, `interrupt`, `rollback`, or `enqueue` (default). |
| **Stream mode** [05] | Which events a streamed run emits: `values`, `updates`, `messages`, `messages-tuple`, `tasks`, `checkpoints`, `events`, `debug`, `custom`. Several can be combined. |
| **Stream resumable** [05] | Run option that persists stream chunks so a client can rejoin a stream after disconnecting. |

### Runtime and infrastructure

| Term | Meaning |
| --- | --- |
| **Agent Server** [00] | The LangChain runtime that hosts graphs and serves the assistants/threads/runs/crons/store API. Ships as the `langgraph-api` package and base image. |
| **API server (API pod)** [06] | A container running `/storage/entrypoint.sh`. Serves HTTP, creates runs, forwards streams. In split mode it has `N_JOBS_PER_WORKER=0` and executes no runs. |
| **`BG_JOB_ISOLATED_LOOPS`** [03, 06] | Runs background jobs on an event loop separate from the API loop. A stopgap for synchronous code, not a fix; splits the Postgres pool per worker. |
| **`BG_JOB_SHUTDOWN_GRACE_PERIOD_SECS`** [06, 09] | How long a shutting-down worker waits for in-flight runs (default 180 s, max 3600 s). Pair with the pod's `terminationGracePeriodSeconds`. |
| **Beacon** [00] | `https://beacon.langchain.com`, the endpoint used for license verification and usage reporting. Egress to it is required unless you hold an offline license. |
| **Distributed runtime** [06] | A third deployment mode where orchestration and execution of a run are separate processes. Mentioned in the docs; not configured in this guide. |
| **KEDA** [06, 07, 08] | Kubernetes Event-Driven Autoscaling. The standalone chart can scale queue pods on a Postgres query counting pending runs; LangSmith Deployments requires KEDA installed. |
| **`LANGGRAPH_CLOUD_LICENSE_KEY`** [00, 07] | The Enterprise license key the containerised server verifies once at startup. Without it (or a LangSmith API key) the server exits after running migrations. |
| **`LANGGRAPH_POSTGRES_POOL_MAX_SIZE`** [06] | Per-replica upper bound on Postgres connections (default 150). Divided per worker when isolated loops are on. |
| **`LANGSMITH_API_KEY` / `LANGSMITH_ENDPOINT`** [00, 07] | Key and self-hosted URL for sending traces to LangSmith. The endpoint must have no trailing slash. |
| **`N_JOBS_PER_WORKER`** [01, 06] | Maximum runs one queue worker executes concurrently (default 10). Bounds run concurrency, not request concurrency. In the chart it is `config.numberOfJobsPerWorker`. |
| **Queue worker (queue pod)** [06] | A container running `/storage/queue_entrypoint.sh`. Claims pending runs from PostgreSQL, executes graphs, writes checkpoints, publishes stream events to Redis. |
| **Redis** [01, 06] | Coordination only: wake-ups, cancellation, stream pub/sub, retry counters. Holds no user or run data. Each deployment needs its own database number. |
| **PostgreSQL** [01, 06] | System of record for every server object, checkpoints (by default) and the store. Each deployment needs its own database name. Version 14 or newer. |
| **Single-host mode** [06] | Default self-hosted mode: API containers also run the queue workers. |
| **Split API and queue** [06] | `queue.enabled: true` in the chart: separate API and worker Deployments that scale independently. |
| **Task queue** [01] | The durable, Postgres-backed queue of pending runs that workers lease from with exactly-once semantics. |

### Deployment paths and platform components

| Term | Meaning |
| --- | --- |
| **`secret_references`** [08] | Control plane API field that populates one environment variable from one key of a Kubernetes Secret already present in the deployment's namespace; how a pipeline hands managed data-store URIs to a deployment without putting them in the request. |
| **`POSTGRES_URI_CUSTOM` / `REDIS_URI_CUSTOM`** [08] | Per-deployment environment variables that make the control plane skip its in-cluster Postgres and Redis and use the managed instances you name. Once set, must stay set for the life of the deployment. |
| **Operator base templates** [08] | The `operator.templates.*` entries in the LangSmith Helm chart from which the operator renders each deployment's Deployment, Service, Redis and Postgres resources. |
| **Compute ID** [08] | The user-chosen identifier of a listener, shown to application teams when they pick where a deployment lands. |
| **Control plane** [00, 08] | The LangSmith component (`host-backend`) with the UI and API for deployments, revisions and listeners. Never connects to the data plane directly; the listener polls it. |
| **Data plane** [00, 08] | Agent Servers plus their PostgreSQL, Redis, secrets and autoscalers, and the listener that reconciles them. |
| **`langgraph-cloud` chart** [07] | The Helm chart for the standalone Agent Server (version 0.3.4 at time of writing). Installs API pods, optional queue pods, bundled or external PostgreSQL, Redis and MongoDB, ingress options, HPA/KEDA and PDBs. |
| **LangGraphPlatform CRD** [08] | The Kubernetes custom resource that represents one LangSmith Deployment; the operator reconciles it into pods and services. |
| **LangSmith Deployments** [00, 08] | The control-plane path: deployments are created in the LangSmith UI or API and provisioned in your cluster by the listener and operator. |
| **Listener** [08] | The data-plane service that polls the control plane for deployments to create, update or delete, and enqueues that work. Bound to one workspace and one listener ID. |
| **Operator** [08] | The Kubernetes operator that turns LangGraphPlatform resources into Deployments, Services, autoscalers and databases. |
| **Revision** [08] | A new version of a LangSmith Deployment: new image URL, environment variables, or settings. Rollback is selecting an earlier revision. |
| **Standalone Agent Server** [00, 07] | The runtime-only path: you run the chart, bring PostgreSQL and Redis, and roll out through your own pipeline. No control plane. |
| **Studio** [02] | The LangSmith web UI for running and debugging a graph against a local or deployed server. |

## Consolidated links

Every documentation page and repository cited anywhere in this guide, deduplicated and grouped. All `docs.langchain.com` links were opened during authoring through the LangChain documentation MCP server.

### Orientation and deployment options

- LangSmith Deployment overview: https://docs.langchain.com/langsmith/deployment
- Deploy to self-hosted (topologies, who manages what): https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview
- Self-host standalone servers: https://docs.langchain.com/langsmith/deploy-standalone-server
- Deep Agents, going to production (uses `langgraph.json`): https://docs.langchain.com/oss/python/deepagents/going-to-production
- Deep Agents, async subagents and worker-pool sizing: https://docs.langchain.com/oss/python/deepagents/async-subagents
- Deploy with control plane: https://docs.langchain.com/langsmith/deploy-with-control-plane
- Enable additional LangSmith features (LangSmith Deployment on self-hosted): https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform
- Self-hosted platform features (custom Postgres and Redis, listeners, resources): https://docs.langchain.com/langsmith/self-hosted-platform-features
- Self-hosted LangSmith Kubernetes install: https://docs.langchain.com/langsmith/kubernetes
- Egress for billing and operational telemetry: https://docs.langchain.com/langsmith/self-host-egress
- Self-hosted dependency versions: https://docs.langchain.com/langsmith/self-host-dependency-versions

### Agent Server concepts and runtime

- Agent Server: https://docs.langchain.com/langsmith/agent-server
- Agent Server overview (capabilities): https://docs.langchain.com/langsmith/agent-server-overview
- Assistants: https://docs.langchain.com/langsmith/assistants
- Use cron jobs: https://docs.langchain.com/langsmith/cron-jobs
- Background runs: https://docs.langchain.com/langsmith/background-run
- Double texting (multitask strategies): https://docs.langchain.com/langsmith/double-texting
- Streaming: https://docs.langchain.com/langsmith/streaming
- Human in the loop: https://docs.langchain.com/langsmith/add-human-in-the-loop
- Configure Agent Server for scale: https://docs.langchain.com/langsmith/agent-server-scale
- Scalability and resilience: https://docs.langchain.com/langsmith/scalability-and-resilience
- LangSmith control plane: https://docs.langchain.com/langsmith/control-plane
- LangSmith data plane: https://docs.langchain.com/langsmith/data-plane
- Agent Server changelog: https://docs.langchain.com/langsmith/agent-server-changelog

### Application structure and configuration

- Application structure: https://docs.langchain.com/langsmith/application-structure
- LangGraph CLI and `langgraph.json` reference: https://docs.langchain.com/langsmith/cli
- `langgraph.json` JSON schema: https://raw.githubusercontent.com/langchain-ai/langgraph/refs/heads/main/libs/cli/schemas/schema.json
- Local development and testing: https://docs.langchain.com/langsmith/local-dev-testing
- Deployment quickstart: https://docs.langchain.com/langsmith/deployment-quickstart
- Rebuild graph at runtime: https://docs.langchain.com/langsmith/graph-rebuild
- Monorepo support: https://docs.langchain.com/langsmith/monorepo-support
- Customize the Dockerfile: https://docs.langchain.com/langsmith/custom-docker
- Deploy other frameworks (Claude Agent SDK, Strands, CrewAI, AutoGen): https://docs.langchain.com/langsmith/deploy-other-frameworks
- Deploy Google ADK: https://docs.langchain.com/langsmith/deploy-google-adk
- Configure checkpointer backend: https://docs.langchain.com/langsmith/configure-checkpointer
- Custom checkpointer: https://docs.langchain.com/langsmith/custom-checkpointer
- Custom store: https://docs.langchain.com/langsmith/custom-store
- Configure TTL: https://docs.langchain.com/langsmith/configure-ttl
- Custom routes: https://docs.langchain.com/langsmith/custom-routes
- Custom middleware: https://docs.langchain.com/langsmith/custom-middleware
- Custom lifespan: https://docs.langchain.com/langsmith/custom-lifespan
- Encryption: https://docs.langchain.com/langsmith/encryption
- Use webhooks: https://docs.langchain.com/langsmith/use-webhooks
- LangGraph persistence and durability modes: https://docs.langchain.com/oss/python/langgraph/persistence

### Authentication and access

- Authentication and access control: https://docs.langchain.com/langsmith/auth
- Add custom authentication: https://docs.langchain.com/langsmith/custom-auth
- Configure IAM authentication for data stores: https://docs.langchain.com/langsmith/configure-iam-auth

### API and SDKs

- Agent Server API reference: https://docs.langchain.com/langsmith/server-api-ref
- Endpoint groups: https://docs.langchain.com/langsmith/agent-server-api/assistants, https://docs.langchain.com/langsmith/agent-server-api/threads, https://docs.langchain.com/langsmith/agent-server-api/thread-runs, https://docs.langchain.com/langsmith/agent-server-api/stateless-runs, https://docs.langchain.com/langsmith/agent-server-api/crons, https://docs.langchain.com/langsmith/agent-server-api/store, https://docs.langchain.com/langsmith/agent-server-api/a2a, https://docs.langchain.com/langsmith/agent-server-api/mcp, https://docs.langchain.com/langsmith/agent-server-api/system
- Control plane API: https://docs.langchain.com/langsmith/api-ref-control-plane
- SDKs and CLI overview: https://docs.langchain.com/langsmith/deploy-reference-overview
- Python SDK: https://docs.langchain.com/langsmith/langgraph-python-sdk
- JS/TS SDK: https://docs.langchain.com/langsmith/langgraph-js-ts-sdk
- RemoteGraph: https://docs.langchain.com/langsmith/remote-graph
- Generative UI in React: https://docs.langchain.com/langsmith/generative-ui-react
- Studio: https://docs.langchain.com/langsmith/studio
- MCP endpoint: https://docs.langchain.com/langsmith/server-mcp
- A2A endpoint: https://docs.langchain.com/langsmith/server-a2a

### Environment variables, metrics and operations

- Self-hosted Agent Server environment variables: https://docs.langchain.com/langsmith/env-var-self-hosted
- Control plane API (deployments, revisions; `/api-host` on self-hosted): https://docs.langchain.com/langsmith/api-ref-control-plane
- LangSmith platform Helm chart values (operator base templates): https://github.com/langchain-ai/helm/blob/main/charts/langsmith/values.yaml
- Self-hosted Agent Server metrics: https://docs.langchain.com/langsmith/self-hosted-agent-server-metrics
- Diagnostics for self-hosted: https://docs.langchain.com/langsmith/diagnostics-self-hosted
- CI/CD pipeline example: https://docs.langchain.com/langsmith/cicd-pipeline-example

### Helm chart (standalone Agent Server)

- Chart directory: https://github.com/langchain-ai/helm/tree/main/charts/langgraph-cloud
- Chart README: https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/README.md
- Default values: https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/values.yaml
- API server Deployment template: https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/templates/api-server/deployment.yaml
- Queue Deployment template: https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/templates/queue/deployment.yaml
- KEDA ScaledObject templates: https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/templates/queue/scaled-object.yaml and https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/templates/api-server/scaled-object.yaml
- Local development with kind: https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/LOCAL_DEVELOPMENT.md
- Helm chart releases: https://github.com/langchain-ai/helm/releases
- Helm repository: https://langchain-ai.github.io/helm

### Tooling

- uv documentation: https://docs.astral.sh/uv/
- Base image tags: https://hub.docker.com/r/langchain/langgraph-server/tags
- Agent Chat UI: https://github.com/langchain-ai/agent-chat-ui
