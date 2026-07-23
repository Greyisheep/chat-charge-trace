#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec uvicorn main:app --reload --port 8000
