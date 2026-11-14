#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"
tools="${MAAS_WORKBENCH_TOOL_CACHE:-$repo/.cache}"
cache="${MAAS_WORKBENCH_GO_CACHE:-$repo/.cache}"
export GOROOT="$tools/go-linux/go" GOMODCACHE="$cache/mod" GOCACHE="$cache/build-linux" GOPATH="$cache/gopath-linux" GOTOOLCHAIN=local GOENV=off GOTELEMETRY=off
export GOFLAGS="${GOFLAGS:--p=4 -buildvcs=false}" GOMAXPROCS="${GOMAXPROCS:-4}"
test -x "$GOROOT/bin/go" || { echo 'Run npm run dev once to prepare the local Go toolchain.' >&2;exit 1; }
exec "$GOROOT/bin/go" "$@"
