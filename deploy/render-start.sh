#!/usr/bin/env bash
# Public-demo start (Render). Copies the read-only snapshot to a writable runtime folder, regenerates the
# deterministic events database, verifies everything, then starts the API in public mode.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA="${GIST_RUNTIME_DIR:-/tmp/gist-data}"
mkdir -p "$DATA"
for name in gist-v2 gist-investigations gist-spend gist-ops; do
  if [ ! -f "$DATA/$name.sqlite3" ]; then cp "deploy/snapshot/$name.sqlite3" "$DATA/$name.sqlite3"; fi
done
if [ ! -f "$DATA/gist-events-v1.sqlite3" ]; then
  python backend/scripts/generate_events.py --db "$DATA/gist-events-v1.sqlite3" --no-answer-key > /dev/null
fi
python deploy/verify_runtime.py "$DATA"

export GIST_DATASET_VERSION=v2
export GIST_DB_PATH="$DATA/gist-v2.sqlite3"
export GIST_EVENTS_DB_PATH="$DATA/gist-events-v1.sqlite3"
export GIST_INVESTIGATIONS_DB_PATH="$DATA/gist-investigations.sqlite3"
export GIST_SPEND_DB_PATH="$DATA/gist-spend.sqlite3"
export GIST_OPS_DB_PATH="$DATA/gist-ops.sqlite3"
export GIST_PRIORITIES_DB_PATH="$DATA/gist-priorities.sqlite3"
export GIST_PUBLIC_MODE="${GIST_PUBLIC_MODE:-true}"          # public by default when deployed
export GIST_TRUST_PROXY="${GIST_TRUST_PROXY:-true}"
export GIST_WARM_CACHES="${GIST_WARM_CACHES:-true}"         # build caches before serving: fast first visit after a wake-up

exec env PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*' --no-server-header
