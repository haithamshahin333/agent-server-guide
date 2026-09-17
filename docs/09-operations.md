# 09. Operations: observe, upgrade, recover, troubleshoot

## Why this matters

Once the Agent Server is running, the platform team owns it: metrics, logs, rollouts, backups and the 2 a.m. page. This module collects the operational facts from the LangChain docs and the Helm chart into one place, adds the failure modes we hit while preparing this guide (with their exact messages), and ends with a pre-production checklist that ties modules 04 to 08 together. It applies to both deployment paths; where the standalone chart and LangSmith Deployments differ, the difference is called out.

## What lives where

Before touching backups or upgrades, be clear about which component holds which state ([Agent Server persistence](https://docs.langchain.com/langsmith/agent-server#persistence), [task queue](https://docs.langchain.com/langsmith/agent-server#task-queue)):

| Component | Holds | Durable? | Loss means |
| --- | --- | --- | --- |
| Postgres | Assistants, threads, runs, cron jobs, the task queue, checkpoints (unless moved to MongoDB), the long-term store | Yes | Loss of all agent state and history. Back it up. |
| MongoDB (optional) | Checkpoints only, when `checkpointer.backend` or `LS_DEFAULT_CHECKPOINTER_BACKEND` is `mongo` | Yes | Loss of thread state; core records in Postgres survive. |
| Redis | Worker wake-ups, cancel signals, streaming pub/sub, resumable stream buffers (`RESUMABLE_STREAM_TTL_SECONDS`, default 120 s) | No | Open streams drop; clients reconnect with `/join` or `/stream`. Nothing to back up. |
| API and queue pods | Nothing | Stateless | Restart freely; in-flight runs resume from the last checkpoint on another worker. |

Backup and disaster recovery therefore reduce to your Postgres (and MongoDB, if used) practice. The docs require Postgres 14 or newer for the standalone chart and 15.8 or newer for `POSTGRES_URI_CUSTOM` under LangSmith Deployments. Each deployment must have its own database (or database name on a shared instance); the same database cannot serve two deployments ([standalone prerequisites](https://docs.langchain.com/langsmith/deploy-standalone-server#prerequisites)). Schema migrations run automatically at pod start-up under a migration lock; the compose run for this guide applied 63 migration versions on an empty database before the server came up, so allow for that on first boot and after upgrades.

## Observability

### Metrics

The server emits OpenTelemetry metrics with the `lg_api_` prefix (override with `METRIC_PREFIX`). There are two sets ([Agent Server metrics](https://docs.langchain.com/langsmith/self-hosted-agent-server-metrics)):

- **Deployment UI metrics** are always emitted and are exposed on `GET /metrics` in Prometheus format by default. Under LangSmith Deployments these power the deployment view in the LangSmith UI.
- **Internal metrics** are operational and debugging series. They go to Datadog when `LSD_DD_API_KEY` is set (endpoint `LSD_DD_ENDPOINT`, default `otlp.us5.datadoghq.com`), and appear on `/metrics` only if `EXPOSE_INTERNAL_METRICS_PROMETHEUS=true`. `METRIC_MAX_EMITTING_TIER` caps which tiers are recorded: 1 CRITICAL, 2 INFO (production default), 3 DEBUG, 4 DEEP_DEBUG.

The Deployment UI set, which is what to scrape first:

| Metric | Type | Tier | Meaning |
| --- | --- | --- | --- |
| `lg_api_http_requests_total` | Counter | INFO | Total HTTP requests |
| `lg_api_http_requests_latency` | Histogram (ms) | INFO | HTTP request latency |
| `lg_api_run_queue_wait_time_1st_attempt` | Histogram (ms) | INFO | Time runs wait in the queue before first processing |
| `lg_api_num_pending_runs` | Gauge | INFO | Runs currently pending |
| `lg_api_num_running_runs` | Gauge | INFO | Runs currently running |
| `lg_api_workers_max` | Gauge | CRITICAL | Maximum worker (job) capacity |
| `lg_api_workers_active` | Gauge | CRITICAL | Jobs currently executing runs |
| `lg_api_workers_available` | Gauge | CRITICAL | Jobs free to accept runs |
| `lg_api_pg_pool_max` | Gauge | CRITICAL | Postgres pool maximum |
| `lg_api_pg_pool_size` | Gauge | CRITICAL | Connections currently managed by the pool |
| `lg_api_pg_pool_available` | Gauge | INFO | Idle Postgres connections |
| `lg_api_pg_pool_requests_queued_total` | Counter | CRITICAL | Connection requests that had to wait for a connection |
| `lg_api_pg_pool_requests_errors_total` | Counter | CRITICAL | Connection request errors (timeouts, queue full) |
| `lg_api_redis_pool_max` | Gauge | INFO | Redis pool maximum |
| `lg_api_redis_pool_size` | Gauge | INFO | Redis connections in use |
| `lg_api_redis_pool_available` | Gauge | INFO | Idle Redis connections |

Internal metrics worth alerting on once exposed: `lg_api_run_failed_after_retry_counter`, `lg_api_run_abandoned_by_shutdown_counter`, `lg_api_failed_to_fetch_runs_counter`, `lg_api_streaming_data_loss_counter`, and the gauge `lg_api_publish_queue_availability` (Redis publish queue health). The full internal list is on the metrics page.

Suggested first alerts, mapped to [module 06](./06-runtime-and-tuning.md):

| Signal | Reads as | Likely action |
| --- | --- | --- |
| `lg_api_run_queue_wait_time_1st_attempt` p95 climbing while `lg_api_workers_available` is 0 | Run capacity exhausted | Add queue workers or raise `N_JOBS_PER_WORKER` |
| `lg_api_http_requests_latency` climbing while workers are idle | Request capacity exhausted | Add API replicas, check Postgres |
| `lg_api_pg_pool_requests_queued_total` increasing | Pool too small for the load | Raise `LANGGRAPH_POSTGRES_POOL_MAX_SIZE` or shrink `N_JOBS_PER_WORKER` under isolated loops |
| `lg_api_num_pending_runs` growing with `lg_api_workers_max` = 0 on every scraped pod | No worker is running (split mode with the queue Deployment down) | Fix the queue Deployment |

Scrape target: the API Service on the port you exposed (`/metrics` on the api-server). In split mode the queue pods emit worker gauges too; scrape them by pod if you want per-worker capacity, since the chart creates no Service for the queue.

### Logs

Set `LOG_JSON=true` on every pod so logs are structured, and `LOG_LEVEL=DEBUG` while investigating ([env vars](https://docs.langchain.com/langsmith/env-var-self-hosted#log_json)). Each log line carries `langgraph_api_version`, `api_variant` (`local_dev`, `licensed`) and, on the Go core lines, the component that logged. The sample values files already set `LOG_JSON`. Under LangSmith Deployments, server logs are also readable in the deployment view once the control plane has RBAC to read pods in the data plane namespace ([read Agent Server logs from other namespaces](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#read-agent-server-logs-from-other-namespaces)).

### Traces to your self-hosted LangSmith

Set on **both** pod types (the queue pods are where graph execution, and therefore most spans, happen):

```yaml
- name: LANGSMITH_ENDPOINT      # hostname of your LangSmith, no trailing slash
  value: https://langsmith.example.internal
- name: LANGSMITH_TRACING       # default true; set "false" to turn tracing off
  value: "true"
```

plus `LANGSMITH_API_KEY` from the chart's secret (key `api_key`). A trailing slash on `LANGSMITH_ENDPOINT` causes authentication errors ([standalone prerequisites](https://docs.langchain.com/langsmith/deploy-standalone-server#prerequisites)). Under LangSmith Deployments the control plane sets the tracing variables itself and creates a tracing project named after the deployment ([deploy with control plane](https://docs.langchain.com/langsmith/deploy-with-control-plane)).

### Application performance monitoring

The image entrypoints (see [module 06](./06-runtime-and-tuning.md#what-the-two-entrypoints-do)) support two APM wrappers, chosen in this order:

1. **Datadog**: set `DD_API_KEY` and the process runs under `ddtrace-run`. `DD_LOGS_ENABLED`, `DD_LOGS_INJECTION`, `DD_TRACE_ENABLED`, `DD_SITE`, `DD_ENV`, `DD_SERVICE`, `DD_TRACE_DEBUG`, `DD_LOG_LEVEL` tune it. The docs note that this can override other auto-instrumentation such as OpenTelemetry ([Datadog variables](https://docs.langchain.com/langsmith/env-var-self-hosted#dd_api_key)).
2. **OpenTelemetry**: set `LS_APM_OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` or `OTEL_EXPORTER_OTLP_ENDPOINT`; both are required on server versions after 0.7.17. Other `OTEL_*` variables apply; the docs suggest `OTEL_PYTHON_EXCLUDED_URLS=/metrics,/ok,/info` to keep probes out of traces. Added in 0.5.32 and marked Alpha ([LS_APM_OTEL_ENABLED](https://docs.langchain.com/langsmith/env-var-self-hosted#ls_apm_otel_enabled)).

## Rollouts and graceful shutdown

Rolling updates of the API tier are ordinary stateless rollouts. The queue tier needs care because a pod may be mid-run:

1. Set `BG_JOB_SHUTDOWN_GRACE_PERIOD_SECS` to cover your longest common run (default 180 s, maximum 3600 s).
2. Set `queue.deployment.terminationGracePeriodSeconds` higher than that value so Kubernetes does not SIGKILL a draining worker. The chart default is 30 s, which is almost certainly too low for the queue tier.
3. Enable `queue.pdb.enabled: true` with `minAvailable: 1` so voluntary disruptions (node drains, cluster upgrades) never leave zero workers. At least one worker must always be listening ([container architecture](https://docs.langchain.com/langsmith/agent-server#container-architecture)).
4. Do not run workers on scale-to-zero or serverless platforms; the docs warn this may cause task loss ([standalone overview](https://docs.langchain.com/langsmith/deploy-standalone-server#overview)).

A run interrupted anyway is retried from its last checkpoint up to `BG_JOB_MAX_RETRIES` (default 3) times; the counter `lg_api_run_abandoned_by_shutdown_counter` tells you how often this happens.

## Upgrades

Pin four things independently and upgrade them deliberately:

| What | Where pinned | How to find the next version |
| --- | --- | --- |
| Your application image | Pipeline writes an immutable tag (git SHA or semver) into `images.apiServerImage.tag` | Your release process |
| Agent Server version inside the image | `base_image` or `api_version` in `langgraph.json` ([module 04](./04-langgraph-json.md)); otherwise `langgraph build` and `langgraph dockerfile` pick the latest `langchain/langgraph-api` for your `python_version` and `image_distro` | [Agent Server changelog](https://docs.langchain.com/langsmith/agent-server-changelog) |
| Helm chart | `--version 0.3.4` on every `helm upgrade` | `helm search repo langchain/langgraph-cloud --versions`, [chart releases](https://github.com/langchain-ai/helm/releases) |
| Postgres and Redis | Your platform | Postgres 14+ (standalone), 15.8+ (`POSTGRES_URI_CUSTOM`) |

Rebuild the image whenever you change `langgraph.json`, because the generated Dockerfile does not update itself. Schema migrations are forward-only and run at start-up, so a rollback with `helm rollback` restores the previous pods but not a previous schema; test upgrades in a non-production namespace first. The chart README records one breaking change to know about: upgrading from chart versions before 0.2.0 requires moving `LANGSMITH_API_KEY` out of `extraEnv` and into the chart secret under the key `api_key` ([chart README](https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/README.md)).

Under LangSmith Deployments, an upgrade of your application is a new revision with a new image URL; the platform components (`host-backend`, `listener`, `operator`) upgrade with the LangSmith Helm chart ([module 08](./08-langsmith-deployments-self-hosted.md)).

## Troubleshooting runbook

Work through the docs' generic steps first ([troubleshooting for self-hosted deployments](https://docs.langchain.com/langsmith/diagnostics-self-hosted)): list what is deployed, enable `LOG_LEVEL=DEBUG`, tail logs, then `kubectl describe` the Deployment and pod and read the `Events:` section for probe failures, image pull errors, resource constraints and volume problems. Then match the symptom below.

### License verification failed

Symptom: API and queue pods start, run migrations, then exit and restart. Captured from the compose stack for this guide (the kind pods logged the same):

```text
[warning] No enterprise license key or LangSmith API key found. To use LangGraph for development,
          please configure a valid LANGSMITH_API_KEY in the environment specified in your langgraph.json file. ...
ValueError: License verification failed. Please ensure proper configuration:
- For local development, set a valid LANGSMITH_API_KEY for an account with LangGraph Cloud access
  in the environment defined in your langgraph.json file.
- For production, configure the LANGGRAPH_CLOUD_LICENSE_KEY environment variable with your LangGraph Cloud license key.
Review your configuration settings and try again. If issues persist, contact support for assistance.
[error] Application startup failed. Exiting.
```

Fixes, in order of likelihood:

1. The secret is empty or missing. In the chart the keys are `api_key` and `langgraph_cloud_license_key` on the secret named by `config.existingSecretName` (or the chart-created `<release>-secrets`). Check with `kubectl get secret <name> -o jsonpath='{.data}'`.
2. The key was put in `extraEnv`. The chart README states this causes license verification failures; remove it and use the secret.
3. No egress to `https://beacon.langchain.com`, which is used for license verification and usage reporting unless you are running in air-gapped mode ([egress](https://docs.langchain.com/langsmith/self-host-egress)).

Note that `langgraph dev` does not perform this check (its log says "No license key or control plane API key set, skipping metadata loop"); the first place you see it is the built image.

Fix 1 is the one that was applied while writing this guide. The Secret was rewritten with a
LangSmith API key in `api_key`, the Deployments were restarted with `kubectl rollout restart deploy`
so the pods re-read the Secret, and every pod became Ready with zero restarts. The successful start
logs a different, informational line that you should expect to see on development deployments:

```text
No enterprise license key found, running in lite mode with LangSmith API key.
For production use, set LANGGRAPH_CLOUD_LICENSE_KEY in environment.
```

Two details matter operationally. A Secret change is not picked up by running pods until they
restart, so an `apply` alone leaves the CrashLoopBackOff in place. And when the chart's `--wait`
timed out on the key-less upgrade, Helm recorded that revision as `failed`; after fixing the Secret
you can either `helm rollback` to the previous good revision or simply upgrade again.

### Pods restart on failed health checks

Symptom: the API pod is killed by its liveness probe under load; logs show slow requests but no crash. Cause named by the docs: synchronous blocking code in a graph node blocking the serving event loop, especially in single-host mode where the API process also executes runs ([BG_JOB_ISOLATED_LOOPS](https://docs.langchain.com/langsmith/env-var-self-hosted#bg_job_isolated_loops)). Fix the code (async clients and drivers, `asyncio.to_thread` for the rest). Interim relief: enable split mode so the API pod no longer executes runs, and only as a last resort `BG_JOB_ISOLATED_LOOPS=true` with a raised `LANGGRAPH_POSTGRES_POOL_MAX_SIZE`. Probe timeouts default to 1 s; raise `timeoutSeconds` in `apiServer.deployment.livenessProbe` only after the cause is understood.

### Runs stay pending

Symptom: `POST /runs` returns immediately, `GET .../runs/{run_id}` shows `pending` forever, `lg_api_num_pending_runs` grows.

- Split mode with no healthy queue pod: check `kubectl get deploy <release>-queue`; the API pods have `N_JOBS_PER_WORKER=0` and will never pick the run up.
- Workers up but saturated: `lg_api_workers_available` is 0 across all workers. Scale the queue tier.
- Workers cannot reach Redis: the wake-up notification never arrives. The queue log should show "Connected to Redis"; if not, check `REDIS_URI` and network policy.
- A run on the same thread is still executing: the queue allows one run per thread at a time; the second waits, or is handled according to its `multitask_strategy`.

### Postgres pool exhaustion

Symptom: `lg_api_pg_pool_requests_queued_total` or `lg_api_pg_pool_requests_errors_total` rising, requests time out, Postgres reports too many connections. Every replica may open up to `LANGGRAPH_POSTGRES_POOL_MAX_SIZE` (default 150) connections; multiply by API plus queue replicas and compare with the database's `max_connections`. Lower the pool size per replica, add a pooler in front of Postgres, or reduce replicas. Under `BG_JOB_ISOLATED_LOOPS` the arithmetic inverts: each worker thread gets only `pool_max // N_JOBS_PER_WORKER` connections, so tiny pools fail on a single stale connection.

### Image pull errors

`kubectl describe pod` shows `ErrImagePull` or `ImagePullBackOff`. For the standalone chart set `images.imagePullSecrets` and, if you mirror, `images.registry`. Under LangSmith Deployments the pull secret is configured once at the platform level in the base agent templates of the LangSmith chart ([private registry authentication](https://docs.langchain.com/langsmith/deploy-with-control-plane#private-registry-authentication)). On kind, side-load with `kind load docker-image` and set `pullPolicy: IfNotPresent`.

### Listens on the wrong address family

Since `langgraph-api` 0.14.0 the server binds IPv4 and IPv6 by default. On a cluster that rejects dual-stack binds, set `LANGGRAPH_SERVER_HOST=0.0.0.0` (IPv4 only) or `::` (IPv6 only) ([LANGGRAPH_SERVER_HOST](https://docs.langchain.com/langsmith/env-var-self-hosted#langgraph_server_host)).

### Graph fails to load at start-up

Symptom: `GraphLoadError: Failed to load graph '<id>' from <path>` followed by "Application startup failed". Seen while building the sample: the `agent` graph constructed its model client at import time, and without a provider key the whole server refused to start, taking the unrelated `echo` graph with it. The server imports every entry in `graphs` at boot; keep module-level code side-effect free, or use a factory function so the failure moves to the individual run ([module 03](./03-existing-project.md)).

### Collecting information for support

Gather the diagnostic bundle described on the support portal, the output of `kubectl get pods`, `kubectl describe pod` for the failing pod, logs with `LOG_LEVEL=DEBUG`, the chart values you applied (secrets redacted) and your `langgraph.json`, plus a description of what you were doing ([support section](https://docs.langchain.com/langsmith/diagnostics-self-hosted#support)).

## Hands-on

On the kind cluster from module 07:

```bash
NS=agent-server
kubectl -n $NS get deploy,pods,svc,secrets
kubectl -n $NS describe deploy agent-server-langgraph-cloud-queue | sed -n '/Environment:/,/Mounts:/p'
P=$(kubectl -n $NS get pod -l app.kubernetes.io/component=agent-server-langgraph-cloud-api-server -o jsonpath='{.items[0].metadata.name}')
kubectl -n $NS logs $P --previous | grep -E 'License|migration lock|Applied database migration' | tail -5
# With a licensed server running:
kubectl -n $NS port-forward svc/agent-server-langgraph-cloud-api-server 8080:80 &
curl -s localhost:8080/metrics | grep -E '^lg_api_(workers|num_pending|pg_pool_max)'
```

## Checkpoint

You can name the four Prometheus series that tell you whether the bottleneck is requests, runs or the database; you can explain why a worker pod needs a longer `terminationGracePeriodSeconds` than the API pod; and you can recognise the license failure, the pending-runs failure and the graph-load failure from their first log line.

## Pre-production checklist

- A `.dockerignore` sits next to `langgraph.json` and the built image contains no `.env`, `.venv` or `.langgraph_api/` under `/deps` ([module 07](./07-standalone-helm-deploy.md#practical-build-rules)).
- If FIPS is required: the image was built with `BASE_IMAGE=...-wolfi-fips`, `openssl-fips-test` passes in the built image, and Postgres and Redis are your own FIPS-mode services ([module 07](./07-standalone-helm-deploy.md#fips-builds)).
Configuration ([module 04](./04-langgraph-json.md))

- [ ] `langgraph.json` pins `python_version`, `image_distro` and either `base_image` or `api_version`.
- [ ] No secrets in `env` inline values; `.env` is git-ignored.
- [ ] Unused route groups disabled (`http.disable_*`), CORS origins restricted, `auth` configured or the ingress enforces authentication.
- [ ] `store` and `checkpointer` TTLs decided.

Runtime ([module 06](./06-runtime-and-tuning.md))

- [ ] Split mode (`queue.enabled: true`) unless traffic is trivially small.
- [ ] `N_JOBS_PER_WORKER` and queue replicas sized with the throughput formula; API replicas sized for request volume.
- [ ] `LANGGRAPH_POSTGRES_POOL_MAX_SIZE × replicas` fits Postgres `max_connections`.
- [ ] `BG_JOB_SHUTDOWN_GRACE_PERIOD_SECS` set and `queue.deployment.terminationGracePeriodSeconds` higher.
- [ ] All application environment variables present on the queue pods.
- [ ] Graph code is asynchronous; no `BG_JOB_ISOLATED_LOOPS` in the values file without a written reason.

Deployment ([module 07](./07-standalone-helm-deploy.md) or [module 08](./08-langsmith-deployments-self-hosted.md))

- [ ] License key and LangSmith API key delivered through a Kubernetes Secret (`api_key`, `langgraph_cloud_license_key`), never `extraEnv`.
- [ ] External Postgres (14+) and Redis with a dedicated database name and Redis database number per deployment.
- [ ] Ingress, gateway or Istio: exactly one enabled, TLS terminated, API Service `ClusterIP`.
- [ ] `images.imagePullSecrets` (standalone) or platform-level pull secrets (LangSmith Deployments) configured.
- [ ] Autoscaling bounds set; KEDA installed if the pending-runs trigger is wanted.
- [ ] Pod disruption budgets on both tiers; at least one worker always available.
- [ ] Egress to `https://beacon.langchain.com` allowed, or the air-gapped arrangement agreed with LangChain.

Operations (this module)

- [ ] `/metrics` scraped; alerts on queue wait time, worker availability, pool queueing, run failures after retry.
- [ ] `LOG_JSON=true` everywhere; `LANGSMITH_ENDPOINT` and `LANGSMITH_TRACING` set on both tiers.
- [ ] Postgres backups and a tested restore; MongoDB backups if used for checkpoints.
- [ ] Upgrade procedure documented: image tag, chart version, base image, with a non-production rehearsal.
- [ ] Runbook entries above adapted to your alerting.

## Gotchas

- `/metrics` from the API Service shows the API pods' view; in split mode the worker capacity gauges live on the queue pods.
- A trailing slash on `LANGSMITH_ENDPOINT` breaks tracing authentication.
- `DD_API_KEY` silently takes precedence over OpenTelemetry instrumentation.
- `helm rollback` does not roll back database migrations.
- Internal metrics never appear on `/metrics` unless `EXPOSE_INTERNAL_METRICS_PROMETHEUS=true`.

## References

- Agent Server metrics (Prometheus, Datadog, tiers, metric tables): https://docs.langchain.com/langsmith/self-hosted-agent-server-metrics
- Troubleshooting for self-hosted deployments: https://docs.langchain.com/langsmith/diagnostics-self-hosted
- Self-hosted Agent Server environment variables: https://docs.langchain.com/langsmith/env-var-self-hosted
- Agent Server persistence and task queue: https://docs.langchain.com/langsmith/agent-server
- Self-host standalone servers (prerequisites, shared instances, scale-to-zero warning): https://docs.langchain.com/langsmith/deploy-standalone-server
- Configure Agent Server for scale: https://docs.langchain.com/langsmith/agent-server-scale
- Egress requirements: https://docs.langchain.com/langsmith/self-host-egress
- Agent Server changelog: https://docs.langchain.com/langsmith/agent-server-changelog
- Read Agent Server logs from other namespaces (LangSmith Deployments): https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#read-agent-server-logs-from-other-namespaces
- Helm chart README (secret keys, upgrade note): https://github.com/langchain-ai/helm/blob/main/charts/langgraph-cloud/README.md
