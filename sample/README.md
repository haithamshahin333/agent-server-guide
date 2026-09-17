# Sample application and deployment assets

This folder holds everything the guide in `../docs` deploys. See the table in the
[top-level README](../README.md#the-sample-project) for what each path is for.

`quickstart-agent/` is the Deep Agent from `docs/00-quickstart.md`; `my-agent/` is the two-graph sample the deep-dive modules use.

Typical loop:

```bash
# develop
cd my-agent && uv sync && uv run pytest && uv run langgraph dev

# build and pre-flight the real server image
cd .. && ./pipeline/build.sh
IMAGE_NAME=my-agent:dev LANGSMITH_API_KEY=... docker compose up -d && curl -s localhost:8123/ok
# or split API + workers locally (port 8124):
docker compose -f docker-compose.split.yml up -d --scale langgraph-queue=2 && curl -s localhost:8124/ok

# deploy to Kubernetes with the standalone Helm chart
KIND_CLUSTER=agent-server-tutorial ./pipeline/push.sh      # or REGISTRY=... for a real registry
VALUES_FILES="helm/values-dev.yaml helm/values-split.yaml" ./pipeline/deploy.sh
./pipeline/smoke.sh
```

For the LangSmith Deployments path (module 08) with managed Postgres and Redis, replace the last two
steps with:

```bash
PG_ADMIN_URI=... PG_APP_USER=... REDIS_HOST=... REDIS_DB=3 DEPLOYMENT_NAME=my-agent K8S_NAMESPACE=agents-prod \
  ./pipeline/provision-datastores.sh
CONTROL_PLANE_HOST=https://<langsmith-host>/api-host LANGSMITH_API_KEY=... WORKSPACE_ID=... \
  LISTENER_COMPUTE_ID=... K8S_NAMESPACE=agents-prod DEPLOYMENT_NAME=my-agent \
  IMAGE_URI=registry.example.internal/platform/my-agent:1.4.0 DATASTORE_SECRET=my-agent-datastores \
  ./pipeline/deploy-control-plane.sh
```

Both scripts are unexercised (no control plane was available while writing) and follow the published API schema.
