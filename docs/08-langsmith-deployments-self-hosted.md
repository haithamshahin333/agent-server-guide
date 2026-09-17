# 08. Deploy through self-hosted LangSmith Deployments

> **Docs-based module.** No self-hosted LangSmith instance was available while writing this guide,
> so nothing here was executed. Every command, screen and behaviour below is taken from the
> LangChain documentation linked in each section, not from captured output. Treat it as a faithful
> reading guide, and verify against your own instance.

[07](./07-standalone-helm-deploy.md) ran the Agent Server image yourself with a Helm chart. This
module takes the **same image, built by the same pipeline**, and hands it to the LangSmith
Deployment control plane that runs inside your self-hosted LangSmith. LangSmith then provisions the
API and queue tiers, their databases, autoscaling and ingress for you, and gives every team a UI with
revisions, logs and metrics.

## Why this matters

With the standalone chart, the platform team owns every Agent Server release: values files, secrets,
scaling, rollout. That is the right shape when one team runs a few agents through its own pipeline.
When many application teams each want to ship agents, the per-release chores multiply. LangSmith
Deployment turns "deploy an agent" into a form in the LangSmith UI (or one API call), while the
containers still run in your cluster, next to your data, on your Postgres and Redis if you choose.
The docs position it as the option for "full data residency or air-gapped" needs with the LangSmith
product experience inside your network
([LangSmith Deployment, common setups](https://docs.langchain.com/langsmith/deployment#common-setups)).

It requires the Enterprise plan with LangSmith Deployment enabled on your instance
([Enable additional LangSmith features](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform)).

## What enabling LangSmith Deployment adds to your cluster

Your self-hosted LangSmith already runs the observability, evaluation and prompt platform. Enabling
Deployment adds four things
([components](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#components),
[diagnostics: key deployed components](https://docs.langchain.com/langsmith/diagnostics-self-hosted#key-deployed-components)):

| Component | Pod name pattern | Role |
| --- | --- | --- |
| Control plane | `langsmith-host-backend` | Receives requests from the LangSmith UI and API, stores the desired state of every deployment and revision in the control plane Postgres. Never connects to the data plane directly. |
| Listener | `langsmith-listener` | Polls `host-backend` over HTTP for deployments to create, update or delete, and enqueues work in `langsmith-redis`. This is the data plane's reconciler. |
| Operator | `langsmith-operator` | A Kubernetes operator for the `LangGraphPlatform` custom resource; turns each CR into the actual Deployments, Services, Secrets and autoscalers of an Agent Server. |
| CRD | `LangGraphPlatform` | The custom resource type that describes one Agent Server instance. |

The UI you already use (`langsmith-frontend`) grows a **Deployments** section that calls
`host-backend` ([control plane UI](https://docs.langchain.com/langsmith/control-plane#control-plane-ui)).

```mermaid
sequenceDiagram
    participant Dev as App team
    participant UI as LangSmith UI / control plane API (/api-host)
    participant CP as host-backend (control plane)
    participant L as listener (data plane)
    participant Op as operator
    participant K as Kubernetes
    Dev->>UI: + New Deployment (image URL, listener, namespace, env)
    UI->>CP: store desired state (deployment + revision 1)
    loop poll
        L->>CP: any deployments to create / update / delete?
        CP-->>L: desired state
    end
    L->>K: create / update LangGraphPlatform CR
    Op->>K: reconcile CR into Deployments, Services, Secrets, autoscalers, Postgres
    K-->>CP: status, logs, metrics (same-cluster RBAC)
    CP-->>Dev: deployment Ready, URL, logs, metrics
```

The docs describe this as the listener reading the control plane's desired state and reconciling the
cluster's current state to match it; the control plane never reaches into the data plane
([data plane listener](https://docs.langchain.com/langsmith/data-plane#listener-application),
[control plane](https://docs.langchain.com/langsmith/control-plane)).

## Prerequisites

From [Enable additional LangSmith features, prerequisites](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#prerequisites):

1. The base LangSmith platform installed with the LangSmith Helm chart
   ([Kubernetes installation guide](https://docs.langchain.com/langsmith/kubernetes)).
2. KEDA installed in the cluster; the docs note it "automatically scales the deployment system
   based on queue size":
   ```bash
   helm repo add kedacore https://kedacore.github.io/charts
   helm upgrade --install keda kedacore/keda --namespace keda --create-namespace
   ```
3. An ingress, Gateway API or Istio setup for the LangSmith instance with a `hostname` set in
   `langsmith_config.yaml`; all agents are exposed as Services behind it
   ([Set up an ingress](https://docs.langchain.com/langsmith/self-host-ingress)).
4. Cluster capacity for multiple deployments; a cluster autoscaler is recommended.
5. A default dynamic StorageClass (`kubectl get storageclass`).
6. Egress to `https://beacon.langchain.com` for license verification
   ([Egress](https://docs.langchain.com/langsmith/self-host-egress)).

## Enable the feature

In your existing `langsmith_config.yaml`
([enable the feature](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#enable-the-feature)):

```yaml
config:
  deployment:
    enabled: true
```

The older `langgraphPlatform` key is deprecated as of chart v0.12.0; use `config.deployment`.

If you mirror images into a private registry, also pin the two new images using the tags from the
[latest LangSmith Helm chart release](https://github.com/langchain-ai/helm/releases):

```yaml
hostBackendImage:
  repository: "docker.io/langchain/hosted-langserve-backend"
  pullPolicy: IfNotPresent
operatorImage:
  repository: "docker.io/langchain/langgraph-operator"
  pullPolicy: IfNotPresent
```

Apply, then confirm the new pods:

```bash
helm upgrade -i langsmith langchain/langsmith --values langsmith_config.yaml --version <version> -n <namespace> --wait --debug
kubectl get pods -n <namespace>
```

If your installation runs the FIPS image set, the operator has a `-fips` counterpart too:
point `operatorImage.repository` at `langchain/langgraph-operator-fips` with the same tag, and build
the agent images themselves from the `-fips` base as shown in
[module 07](./07-standalone-helm-deploy.md#fips-builds)
([FIPS-compliant images](https://docs.langchain.com/langsmith/self-host-fips)).

### Private registries for agent images

Your agent images will live in your registry. Because the **operator** creates the Agent Server
pods, the pull secret must be set in the operator's deployment template, once, at the
infrastructure level. Every deployment created through the UI then inherits it
([Configure authentication for private registries](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#configure-authentication-for-private-registries)):

```bash
kubectl create secret docker-registry langsmith-registry-secret \
    --docker-server=myregistry.com --docker-username=... --docker-password=... \
    --docker-email=... -n langsmith
```

```yaml
operator:
  templates:
    deployment: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: ${name}
        namespace: ${namespace}
      spec:
        replicas: ${replicas}
        revisionHistoryLimit: 10
        selector:
          matchLabels:
            app: ${name}
        template:
          metadata:
            labels:
              app: ${name}
          spec:
            enableServiceLinks: false
            imagePullSecrets:
            - name: langsmith-registry-secret
            containers:
            - name: api-server
              image: ${image}
              ports:
              - name: api-server
                containerPort: 8000
                protocol: TCP
              livenessProbe:
                httpGet: { path: /ok, port: 8000 }
                periodSeconds: 15
                timeoutSeconds: 5
                failureThreshold: 6
              readinessProbe:
                httpGet: { path: /ok, port: 8000 }
                periodSeconds: 15
                timeoutSeconds: 5
                failureThreshold: 6
```

This template is the same mechanism you would use to customise anything the operator stamps onto
every agent pod (node selectors, annotations, sidecars); the docs point at the base agent templates
in the LangSmith chart's `values.yaml` for the full set
([configure base agent templates](https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform#enable-the-feature)).

## Hands-on (from the docs): deploy the sample image

The workflow in [Deploy with control plane](https://docs.langchain.com/langsmith/deploy-with-control-plane)
has four steps. The first three are exactly the pipeline from module 07.

### 1. Test locally

```bash
cd sample/my-agent && uv run langgraph dev
```

### 2. Build the image

Either `langgraph build -t registry.example.internal/platform/my-agent:1.4.0` or the
`build.sh` route from [07](./07-standalone-helm-deploy.md#build-the-image-in-your-own-pipeline).
The docs' `langgraph build` options:

| Option | Default | Description |
| --- | --- | --- |
| `-t, --tag TEXT` | required | Tag for the image |
| `--platform TEXT` | | Target platform(s), e.g. `linux/amd64,linux/arm64` |
| `--pull / --no-pull` | `--pull` | Build against the latest remote base image |
| `-c, --config FILE` | `langgraph.json` | Config file path |

### 3. Push to a registry the cluster can pull from

```bash
REGISTRY=registry.example.internal/platform IMAGE_TAG=1.4.0 ./sample/pipeline/push.sh
```

The docs recommend version tags (`my-registry.com/my-app:v1.0.0`) so rollbacks are a matter of
pointing a revision at an older tag.

### 4. Create the deployment in the LangSmith UI

1. Left navigation, **Deployments**.
2. Top right, **+ New Deployment**.
3. Fill in:
   - **Image URL**: the full reference you pushed.
   - **Listener / Compute ID**: the listener configured for your cluster.
   - **Namespace**: the Kubernetes namespace to deploy into.
   - **Environment variables**: model keys, `MODEL`, and anything else the graphs read. You do
     **not** set `LANGCHAIN_TRACING` or `LANGSMITH_API_KEY`; the control plane injects them
     ([LangSmith integration](https://docs.langchain.com/langsmith/control-plane#langsmith-integration)).
   - Other settings as needed (resources, replicas, see below).
4. **Submit**.

What happens next is asynchronous. The listener picks up the new deployment, the operator creates
the resources, and on the **first** revision a dedicated PostgreSQL database is created, which is why
the initial rollout takes longest; later revisions skip that step. Each revision also includes a
build step. Expect "up to several minutes"
([asynchronous deployment](https://docs.langchain.com/langsmith/control-plane#asynchronous-deployment)).

Once Ready, the deployment page shows build logs, server logs, and charts for CPU and memory,
container restarts, replica count, PostgreSQL CPU/memory/disk, queue pending and active run counts,
and API success, error and latency counts
([monitoring](https://docs.langchain.com/langsmith/control-plane#monitoring)). A LangSmith tracing
project with the deployment's name is created automatically; deleting the deployment keeps the
traces.

### 5. Ship a new version: create a revision

A **revision** is an iteration of a deployment. Code changes and secret updates both require a new
revision ([revisions](https://docs.langchain.com/langsmith/control-plane#revisions)). From the
deployment page: **+ New Revision**, update the **Image URL** to the new tag, adjust environment
variables, **Submit** ([update deployment](https://docs.langchain.com/langsmith/deploy-with-control-plane#update-deployment)).
Rolling back is a revision that points at the previous tag.

### 6. Call it

The deployed server exposes the same API you used in [05](./05-api-surface.md), behind your
LangSmith ingress hostname. Use the SDKs, `RemoteGraph`, plain REST or Studio
([connect to your deployed agent](https://docs.langchain.com/langsmith/cicd-pipeline-example#connect-to-your-deployed-agent)).

## Self-hosted-only knobs

These apply to deployments created through the control plane and are documented in
[Self-hosted platform features](https://docs.langchain.com/langsmith/self-hosted-platform-features).

### Data stores: what the control plane provisions, and how to use managed services instead

This is the question platform teams ask first, because it is the one place the two paths really
differ. With the standalone chart you decide once, per Helm release, whether Postgres and Redis are
bundled or external ([module 07](./07-standalone-helm-deploy.md)). With the control plane, every
"New Deployment" click provisions data stores *dynamically*, so the platform team needs a policy
for where those stores come from.

**What happens by default.** When a deployment is created, the operator renders its resources from
base templates in the LangSmith Helm chart (`operator.templates.*` in
[`charts/langsmith/values.yaml`](https://github.com/langchain-ai/helm/blob/main/charts/langsmith/values.yaml)).
Two of those templates are data stores, created *per deployment* inside the deployment's namespace:

| Template | What it creates | Notes (from the chart) |
| --- | --- | --- |
| `operator.templates.db` | A one-pod Postgres `StatefulSet` from `pgvector/pgvector:pg15` with a `PersistentVolumeClaim` of `${storage_gi}Gi` and `max_connections` set from the deployment spec | PVC retention is `whenDeleted: Delete`, so the data is removed with the deployment. This is why the prerequisites demand a default `StorageClass` and why the docs say first deployments take longer "due to database creation". |
| `operator.templates.redis` | A one-replica Redis `Deployment` from `docker.io/redis:7`, no persistence | Adequate, because Redis holds only ephemeral queue and stream data ([module 01](./01-concepts.md)). |

That default is convenient for development namespaces and preview deployments. For production you
usually want managed services with backups, high availability and your own operational tooling,
and the control plane supports that with two per-deployment environment variables
([`POSTGRES_URI_CUSTOM`](https://docs.langchain.com/langsmith/env-var-self-hosted#postgres_uri_custom),
[`REDIS_URI_CUSTOM`](https://docs.langchain.com/langsmith/env-var-self-hosted#redis_uri_custom),
[Self-hosted platform features](https://docs.langchain.com/langsmith/self-hosted-platform-features)):

```bash
POSTGRES_URI_CUSTOM="postgresql://user:pass@pg.example.internal:5432/agent_server_a?sslmode=require"
REDIS_URI_CUSTOM="rediss://redis.example.internal:6379/1"
```

The docs state the contract precisely, and each line matters operationally:

- If `POSTGRES_URI_CUSTOM` is set, the control plane does **not** provision a database for that server.
- Postgres must be version 15.8 or higher, and the database named in the URI must already exist.
- Once set, it must stay set for the life of the deployment. Removing it does not make the control plane provision a database; the revision simply fails to deploy.
- Deleting the deployment does not delete the external database. Backups, retention and cleanup are yours.
- The value can be updated (a rotated password, for example) by creating a new revision.
- Network reachability from the Agent Server pods to the store is your responsibility.

Sharing is allowed with the same rule as the standalone server: one managed Postgres instance can
back many deployments, each with its **own database name**; one Redis can back many deployments,
each with its **own database number**. The same database or db number must never be shared.

**There is no cluster-wide switch.** The chart's `config.deployment` block only controls
`enabled`, `basePath`, `tlsEnabled`, `ingressHealthCheckEnabled` and `uncappedResourcesEnabled`
(values reviewed at the time of writing); nothing there says "use RDS for every deployment".
Managed stores are an input to each deployment. The way to make that input reliable, repeatable
and reviewable is to let the **pipeline that already builds the image also provision the data
stores and create the deployment**. That is the pattern this guide recommends for teams that want
cloud dependencies behind their control plane deployments, and the rest of this section is built
around it. (The manual alternative, a platform team handing URIs to application teams to paste into
"New Deployment", works at low volume and needs no further explanation.)

### The pipeline pattern: provision, then deploy through the API

```mermaid
sequenceDiagram
    autonumber
    participant CI as Your pipeline
    participant PG as Managed Postgres<br/>(RDS, Azure PG, Cloud SQL)
    participant RD as Managed Redis
    participant K8s as Target namespace
    participant CP as Control plane<br/>(/api-host on your LangSmith)
    participant L as Listener + operator
    CI->>CI: build image, push to registry
    CI->>PG: CREATE DATABASE <deployment> (once)
    CI->>RD: allocate a db number (once)
    CI->>K8s: Secret <deployment>-datastores<br/>postgres_uri, redis_uri
    CI->>CP: POST /v2/deployments (external_docker,<br/>image_uri, listener_id, namespace,<br/>secret_references -> POSTGRES_URI_CUSTOM, REDIS_URI_CUSTOM)
    CP-->>CI: id, latest_revision_id
    L->>CP: poll for desired state
    L->>K8s: create API + queue pods from the image<br/>(no in-cluster Postgres or Redis)
    CI->>CP: GET revision until status = DEPLOYED
    CI->>CP: later: PATCH image_uri = new tag (new revision)
```

The sample repo carries this as two scripts, `sample/pipeline/provision-datastores.sh` and
`sample/pipeline/deploy-control-plane.sh`. They were written against the published OpenAPI schema
and could not be run here (no self-hosted control plane was available), so read them as a
reviewed starting point rather than captured output.

**Step 1: provision once per deployment.** `provision-datastores.sh` connects to the managed
Postgres *instance* with an admin URI, creates the application role and a database named after the
deployment if they do not exist, takes a Redis database number you allocate, and writes both
connection URIs into a Kubernetes Secret in the target namespace with the keys `postgres_uri` and
`redis_uri`. Two rules from the docs shape it: the database must exist before the deployment is
created, and the instance may be shared but the database name and the Redis db number must be
unique per deployment. Record the db number allocation somewhere durable; the control plane does
not track it for you.

**Step 2: create or update the deployment through the API.** `deploy-control-plane.sh` resolves
the listener from its Compute ID (`GET /v2/listeners`, checking that the target namespace is in the
listener's `k8s_namespaces`), then sends the request that the UI would build for you. This is the
body for an image-based deployment on self-hosted, with the fields that matter to the data-store
question highlighted by their position:

```json
{
  "name": "my-agent",
  "source": "external_docker",
  "source_config": {
    "listener_id": "<from GET /v2/listeners>",
    "listener_config": { "k8s_namespace": "agents-prod" },
    "resource_spec": { "min_scale": 2, "max_scale": 6, "cpu": 1, "memory_mb": 2048,
                       "queue_min_scale": 2, "queue_max_scale": 10,
                       "service_account_name": "my-agent" }
  },
  "source_revision_config": { "image_uri": "registry.example.internal/platform/my-agent:1.4.0" },
  "secrets": [ { "name": "OPENAI_API_KEY", "value": "..." } ],
  "secret_references": [
    { "name": "POSTGRES_URI_CUSTOM", "secret_name": "my-agent-datastores", "secret_key": "postgres_uri" },
    { "name": "REDIS_URI_CUSTOM",    "secret_name": "my-agent-datastores", "secret_key": "redis_uri" }
  ]
}
```

Three things about this body are worth understanding:

- `secret_references` is the mechanism that keeps database credentials out of the API call and
  out of the control plane's own storage. Each entry populates one environment variable from one
  key of a Kubernetes Secret that already exists in the deployment's namespace
  ([Create Deployment](https://docs.langchain.com/api-reference/deployments-v2/create-deployment)).
  Inline `secrets` are also environment variables, and are the right place for values the control
  plane should own, such as model keys. Both fields trigger a new revision when changed.
- Because `POSTGRES_URI_CUSTOM` is present, the control plane does not create the in-cluster
  Postgres for this deployment, and the `db_*` fields of `resource_spec` are irrelevant. The same
  goes for Redis with `REDIS_URI_CUSTOM`.
- `listener_id` and `listener_config.k8s_namespace` cannot be changed after creation, and the
  docs say `POSTGRES_URI_CUSTOM` must stay set for the deployment's life. The script therefore
  creates with the full body and updates with `PATCH /v2/deployments/{id}` carrying only the new
  `image_uri` (and any changed secrets), which is what produces a new revision.

**Step 3: wait for the revision.** The pipeline polls
`GET /v2/deployments/{id}/revisions/{revision_id}` until `status` is `DEPLOYED`, failing on
`CREATE_FAILED`, `BUILD_FAILED`, `DEPLOY_FAILED` or `INTERRUPTED`; the other values you will see in
between are `CREATING`, `QUEUED`, `AWAITING_DEPLOY` and `DEPLOYING`
([Get Revision](https://docs.langchain.com/api-reference/deployments-v2/get-revision)). This
replaces the `helm --wait` step of the standalone path. First deployments no longer wait on
database creation, since the database already exists.

**Rotation and lifecycle.** A rotated password is a new value in the Kubernetes Secret followed
by a new revision (re-run the deploy script; pods restart and re-read the reference). Deleting the
deployment never drops the managed database, so decommissioning is a separate, deliberate pipeline
step. The database name and Redis db number stay reserved until you free them.

**Workload identity instead of passwords.** With managed stores already in the pipeline's hands,
the step up is to drop static passwords: enable IAM or Entra authentication on the store, put the
principal name in the URI with no password, and add `AGENT_POSTGRES_IAM_AUTH_PROVIDER` and
`AGENT_REDIS_IAM_AUTH_PROVIDER` (`aws`, `azure` or `gcp`) to the inline `secrets`
([Configure IAM authentication](https://docs.langchain.com/langsmith/configure-iam-auth), whose
table maps the control plane case to exactly `POSTGRES_URI_CUSTOM` and `REDIS_URI_CUSTOM`). The
credentials must reach every API and queue pod, which is what `resource_spec.service_account_name`
is for: create the ServiceAccount in the namespace ahead of time, bind the cloud identity to it
(IRSA or Pod Identity, Azure Workload Identity, GKE Workload Identity), and name it in the request.
Use `sslmode=require` and `rediss://`, and set `REDIS_CLUSTER=true` for cluster-mode Redis.

For comparison, the standalone path sets the same two connections once per Helm release
(`postgres.external.connectionUrl` or `existingSecretName`, and the Redis equivalent), so a
platform team that already runs managed stores for standalone servers can reuse the exact same
instances for control plane deployments; only the per-deployment database names and db numbers
are new.

## Automate it from your pipeline

The UI steps map onto the control plane API, which on a self-hosted instance lives under your
LangSmith hostname at the `/api-host` path, for example `https://<host>/api-host/v2/deployments`.
Authenticate with `X-Api-Key` (a LangSmith API key) and `X-Tenant-Id` (the workspace ID)
([Control plane API reference](https://docs.langchain.com/langsmith/api-ref-control-plane)). The
endpoint groups are Deployments (v2), Listeners (v2), Integrations (v1) and Auth Service (v2).

For a self-hosted team the sequence is the one the docs give for deploying from your own container registry
([Method 2: Control plane API](https://docs.langchain.com/langsmith/cicd-pipeline-example#method-2-control-plane-api)),
with the data-store step from the previous section added in front of the API call:

```bash
./sample/pipeline/build.sh                       # langgraph dockerfile + docker build
REGISTRY=registry.example.internal ./sample/pipeline/push.sh
./sample/pipeline/provision-datastores.sh        # managed Postgres database, Redis db number, Secret
./sample/pipeline/deploy-control-plane.sh        # POST or PATCH /v2/deployments, poll to DEPLOYED
```

The first two scripts are shared with the standalone path in [module 07](./07-standalone-helm-deploy.md);
only the last step differs (`helm upgrade` there, an HTTP call here). The `external_docker` request
body the script sends is shown in full in the previous section. A common mistake the docs call out:
sending deployment requests to the LangSmith tracing API instead of `/api-host`. Keep the two base
URLs distinct in your pipeline variables.

## Checkpoint

You should now be able to:

- name the four components enabling Deployment adds (`host-backend`, `listener`, `operator`,
  `LangGraphPlatform` CRD) and describe the poll-and-reconcile loop between them;
- turn the feature on with `config.deployment.enabled: true`, KEDA and an ingress hostname in
  place;
- configure a private registry once in the operator template;
- take an image from your pipeline through **+ New Deployment** and **+ New Revision**;
- point a deployment at your own Postgres and Redis with `POSTGRES_URI_CUSTOM` and
  `REDIS_URI_CUSTOM`;
- find the control plane API at `/api-host` and know which headers it needs.

Verifying command, on your instance after enabling the feature:

```bash
kubectl get pods -n <langsmith-namespace> | grep -E 'host-backend|listener|operator'
kubectl get crd | grep -i langgraphplatform
```

## Choosing between the two paths

| | Standalone Agent Server (module 07) | LangSmith Deployments (this module) |
| --- | --- | --- |
| Who reconciles a release | Your pipeline, via `helm upgrade` | The listener and operator, from control plane state |
| Where env vars and secrets live | Helm values and Kubernetes Secrets you manage | Deployment / revision settings in the UI or API; tracing vars injected for you |
| Where scaling is set | `apiServer` / `queue` replicas, HPA or KEDA in values | Resources and replicas per deployment; KEDA required cluster-wide |
| Databases | Bring your own, or the chart's bundled dev instances | Provisioned per deployment, or `POSTGRES_URI_CUSTOM` / `REDIS_URI_CUSTOM` |
| Rollback | `helm rollback` to a recorded revision | New revision pointing at the previous image tag |
| Logs and metrics | Your logging and Prometheus stack (`/metrics`) | In the LangSmith UI, plus your stack |
| Multi-team ergonomics | Each agent is a Helm release the platform team owns | Self-service: any workspace member with access can create deployments |
| Prerequisites | Helm chart, license key, Postgres, Redis | Enterprise LangSmith with Deployment enabled, KEDA, ingress hostname |
| Moving parts | Two Deployments per agent | Control plane, listener, operator, CRD, plus two Deployments per agent |

A practical heuristic: choose the **standalone** server when the platform team owns rollout through
its own pipeline, wants the fewest moving parts, or needs the runtime embedded in existing
infrastructure or air-gapped environments. Choose **LangSmith Deployments** when many application
teams need self-service deploys, revisions, logs and metrics in one UI, and you are willing to run the
control plane components alongside LangSmith. Both run the same image from the same pipeline, so the
choice is reversible.

## Gotchas

- **Two base URLs.** Tracing goes to `https://<host>` (or `/api`); deployment automation goes to
  `https://<host>/api-host`. Mixing them is the docs' named failure mode.
- **Registry credentials are infrastructure, not per deployment.** Set `imagePullSecrets` in the
  operator template; the New Deployment form has no field for them.
- **First revision is slow.** Database creation happens once per deployment; do not treat a
  multi-minute first rollout as a failure.
- **Do not set tracing variables yourself.** The control plane sets `LANGCHAIN_TRACING` and the
  API key per deployment.
- **Cross-cluster logs are unsupported.** Keep control plane and data plane in one cluster if the
  UI's server logs matter to you; otherwise rely on your own log pipeline.
- **Additional data planes are on the way out.** For agents in other clusters, the docs now steer
  you to standalone servers that trace back to LangSmith.

## References

- Deploy with control plane: <https://docs.langchain.com/langsmith/deploy-with-control-plane>
- Enable additional LangSmith features (LangSmith Deployment): <https://docs.langchain.com/langsmith/deploy-self-hosted-full-platform>
- LangSmith control plane: <https://docs.langchain.com/langsmith/control-plane>
- LangSmith data plane: <https://docs.langchain.com/langsmith/data-plane>
- Self-hosted platform features: <https://docs.langchain.com/langsmith/self-hosted-platform-features>
- Control plane API reference: <https://docs.langchain.com/langsmith/api-ref-control-plane>
- CI/CD pipeline example: <https://docs.langchain.com/langsmith/cicd-pipeline-example>
- Diagnostics for self-hosted (key deployed components): <https://docs.langchain.com/langsmith/diagnostics-self-hosted>
- Configure IAM authentication for data stores: <https://docs.langchain.com/langsmith/configure-iam-auth>
- Deploy to self-hosted overview: <https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview>
- Kubernetes installation guide for LangSmith: <https://docs.langchain.com/langsmith/kubernetes>
- Control plane API: Create Deployment (`external_docker`, `secret_references`): https://docs.langchain.com/api-reference/deployments-v2/create-deployment
- Control plane API: Get Revision (status values): https://docs.langchain.com/api-reference/deployments-v2/get-revision
- Control plane API: List Listeners: https://docs.langchain.com/api-reference/listeners-v2/list-listeners
