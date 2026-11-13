#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"
export GOROOT="$repo/.cache/go-linux/go" GOMODCACHE="$repo/.cache/mod" GOCACHE="$repo/.cache/build-linux" GOTOOLCHAIN=local GOENV=off
test -x "$GOROOT/bin/go" || { echo 'Run npm run dev once to prepare the local Go toolchain.' >&2;exit 1; }
exec "$GOROOT/bin/go" "$@"
