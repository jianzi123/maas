#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$task_root"
export GOROOT="$task_root/.cache/go-linux/go"
export GOPATH="$task_root/.cache/gopath-linux" GOMODCACHE="$task_root/.cache/mod" GOCACHE="$task_root/.cache/build-linux"
export GOTOOLCHAIN=local GOENV=off
"$GOROOT/bin/gofmt" -w test/acceptance/kernel_cases_test.go.in
"$GOROOT/bin/go" test ./... -json -count=1 > artifacts/qa-go-regression.json
