#!/usr/bin/env bash
set -euo pipefail

base_url="${BACKEND_LOCAL_URL:-http://127.0.0.1:8001}"
paths=(
  "/health"
  "/api/settings"
  "/api/goals"
  "/api/dashboard/core"
  "/api/nutrition/today"
  "/api/training/history?limit=25&days=180"
  "/api/debug/startup"
)

for path in "${paths[@]}"; do
  tmp="$(mktemp)"
  meta="$(curl -sS -o "$tmp" -w "HTTP %{http_code} time %{time_total}s" "${base_url}${path}")"
  printf "\n== %s ==\n%s\n" "$path" "$meta"
  python3 -m json.tool "$tmp" | sed -n '1,80p'
  rm -f "$tmp"
done
