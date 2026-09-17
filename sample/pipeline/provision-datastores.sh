#!/usr/bin/env bash
# provision-datastores.sh : create the per-deployment database on a managed Postgres instance,
# allocate a Redis database number on a managed Redis, and store both connection URIs in a
# Kubernetes Secret in the namespace the control plane will deploy into.
#
# Run this BEFORE deploy-control-plane.sh. It is idempotent: an existing database or Secret is
# left in place and the Secret is updated to the current URIs.
#
# Inputs (environment variables):
#   PG_ADMIN_URI       admin connection to the managed Postgres INSTANCE (not the app database),
#                      e.g. postgresql://admin:pw@pg.example.internal:5432/postgres?sslmode=require
#   PG_APP_USER        application role that will own the database (created if missing)
#   PG_APP_PASSWORD    its password (omit when using IAM auth; see module 08)
#   REDIS_HOST         managed Redis endpoint, e.g. redis.example.internal
#   REDIS_DB           database NUMBER reserved for this deployment (0-15 by default on Redis;
#                      each deployment needs its own)
#   DEPLOYMENT_NAME    used as the database name (lowercased, dashes to underscores)
#   K8S_NAMESPACE      namespace the deployment will land in
#   DATASTORE_SECRET   Kubernetes Secret to write (default: <deployment>-datastores)
#
# Requirements from the docs (env-var-self-hosted#postgres_uri_custom): Postgres 15.8 or higher,
# and the database named in POSTGRES_URI_CUSTOM must already exist. Once a deployment has been
# created with POSTGRES_URI_CUSTOM it must keep it for its whole life.
#
# NOT EXERCISED while writing the guide (no self-hosted control plane was available).
set -euo pipefail

: "${PG_ADMIN_URI:?set PG_ADMIN_URI}"
: "${PG_APP_USER:?set PG_APP_USER}"
: "${REDIS_HOST:?set REDIS_HOST}"
: "${REDIS_DB:?set REDIS_DB}"
: "${DEPLOYMENT_NAME:?set DEPLOYMENT_NAME}"
: "${K8S_NAMESPACE:?set K8S_NAMESPACE}"
DATASTORE_SECRET="${DATASTORE_SECRET:-${DEPLOYMENT_NAME}-datastores}"

DB_NAME="$(echo "$DEPLOYMENT_NAME" | tr '[:upper:]-' '[:lower:]_')"
PG_HOSTPORT="$(python3 -c 'import sys,urllib.parse as u; p=u.urlparse(sys.argv[1]); print(f"{p.hostname}:{p.port or 5432}")' "$PG_ADMIN_URI")"

echo "==> Ensuring role ${PG_APP_USER} and database ${DB_NAME} exist on ${PG_HOSTPORT}"
if [ -n "${PG_APP_PASSWORD:-}" ]; then
  psql "$PG_ADMIN_URI" -v ON_ERROR_STOP=1 -qtAc \
    "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${PG_APP_USER}') THEN CREATE ROLE ${PG_APP_USER} LOGIN PASSWORD '${PG_APP_PASSWORD}'; END IF; END \$\$;"
  PG_CRED="${PG_APP_USER}:${PG_APP_PASSWORD}"
else
  # IAM / workload identity: role exists with rds_iam (AWS) or the Entra/ADC equivalent; no password.
  PG_CRED="${PG_APP_USER}"
fi
if [ "$(psql "$PG_ADMIN_URI" -qtAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")" != "1" ]; then
  psql "$PG_ADMIN_URI" -v ON_ERROR_STOP=1 -qtAc "CREATE DATABASE ${DB_NAME} OWNER ${PG_APP_USER}"
  echo "    created database ${DB_NAME}"
else
  echo "    database ${DB_NAME} already exists"
fi

POSTGRES_URI_CUSTOM="postgresql://${PG_CRED}@${PG_HOSTPORT}/${DB_NAME}?sslmode=require"
REDIS_URI_CUSTOM="rediss://${REDIS_HOST}:6379/${REDIS_DB}"

echo "==> Writing Secret ${K8S_NAMESPACE}/${DATASTORE_SECRET} (keys: postgres_uri, redis_uri)"
kubectl -n "$K8S_NAMESPACE" create secret generic "$DATASTORE_SECRET" \
  --from-literal=postgres_uri="$POSTGRES_URI_CUSTOM" \
  --from-literal=redis_uri="$REDIS_URI_CUSTOM" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "DATASTORE_SECRET=${DATASTORE_SECRET}"
echo "REDIS_DB=${REDIS_DB} (record this allocation; the same number must never be reused for another deployment)"
