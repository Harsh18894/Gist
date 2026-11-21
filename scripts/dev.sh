#!/bin/sh
set -eu

if [ ! -x .venv/bin/uvicorn ]; then
  echo "Gist API dependencies are missing. Run: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt" >&2
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "Gist frontend dependencies are missing. Run: (cd frontend && npm install)" >&2
  exit 1
fi

PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8000 &
api_pid=$!

cleanup() {
  kill "$api_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

npm --prefix frontend run dev
