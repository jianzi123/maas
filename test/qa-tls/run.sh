#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
: "${MAAS_TEST_GO_ROOT:?explicit approved Linux Go1.26 required}"
export GOROOT="$MAAS_TEST_GO_ROOT" GOENV=off GOTOOLCHAIN=local GOMAXPROCS=4
export GOMODCACHE="${MAAS_TEST_GOMODCACHE:-$root/.cache/mod}" GOCACHE="${MAAS_TEST_GOCACHE:-$root/.cache/build-linux}"
mkdir -p artifacts
"$GOROOT/bin/gofmt" -w test/qa-tls/factory_test.go.in
python3 - <<'PY'
from pathlib import Path
import json
r=Path.cwd();(r/'artifacts/qa-overlay.json').write_text(json.dumps({'Replace':{str(r/'internal/kernel/qa_tls_test.go'):str(r/'test/qa-tls/factory_test.go.in')}}))
PY
export GOFLAGS="-p=4 -overlay=$root/artifacts/qa-overlay.json"
"$GOROOT/bin/go" test ./internal/kernel -run '^(TestQATLSFactory|TestRelayTLSRuntime)$' -count=1 -v -timeout=90s > artifacts/qa-tls.txt 2>&1