#!/usr/bin/env bash
# Docker wrapper for build machines behind a TLS-inspecting HTTPS proxy (e.g. Claude Code's cloud
# sessions). Use it as `WRANGLER_DOCKER_BIN=tools/docker-proxy.sh npx wrangler deploy`.
# It adds host networking, the proxy settings and the proxy's CA (as a build secret) to `docker build`;
# every other docker command passes through unchanged.
set -euo pipefail
CA="${PROXY_CA_BUNDLE:-/root/.ccr/ca-bundle.crt}"
if [[ "${1:-}" == "build" || ( "${1:-}" == "buildx" && "${2:-}" == "build" ) ]]; then
  extra=(--network host)
  [[ -f "$CA" ]] && extra+=(--secret "id=proxy_ca,src=$CA")
  for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
    [[ -n "${!v:-}" ]] && extra+=(--build-arg "$v=${!v}")
  done
  if [[ "$1" == "buildx" ]]; then shift 2; exec docker buildx build "${extra[@]}" "$@"; fi
  shift; exec docker build "${extra[@]}" "$@"
fi
exec docker "$@"
