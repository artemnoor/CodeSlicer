#!/bin/sh
set -eu

# Compose exposes this container only on host loopback. The token is injected
# into that locally served SPA so it can call the intentionally remote-bound
# container API; never use this profile with a public port mapping.
if [ "${1:-}" = "impact-engine-local-api" ]; then
  : "${IMPACT_LOCAL_API_TOKEN:?IMPACT_LOCAL_API_TOKEN is required for the Docker Local UI}"
  printf 'window.CODE_SLICER_REMOTE_TOKEN=%s;\n' "$(printf '%s' "$IMPACT_LOCAL_API_TOKEN" | python -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" > /app/frontend/runtime-config.js
fi
exec "$@"
