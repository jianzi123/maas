#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
: "${MAAS_TEST_GO_ROOT:?explicit approved Linux Go1.26 required}"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit approved MySQL8.4.7 task cache required}"
export GOROOT="$MAAS_TEST_GO_ROOT" GOENV=off GOTOOLCHAIN=local
export GOMODCACHE="${MAAS_TEST_GOMODCACHE:-$root/.cache/mod}" GOCACHE="${MAAS_TEST_GOCACHE:-$root/.cache/build-linux}"
mkdir -p artifacts
"$GOROOT/bin/gofmt" -w test/qa-usage/*.go.in
python3 - <<'PY'
from pathlib import Path
import json
r=Path.cwd()
(r/'artifacts/qa-overlay.json').write_text(json.dumps({'Replace':{str(r/'internal/kernel/qa_usage_test.go'):str(r/'test/qa-usage/kernel_test.go.in'),str(r/'cmd/control-api/qa_reader_test.go'):str(r/'test/qa-usage/reader_test.go.in')}}))
PY
export GOFLAGS="-overlay=$root/artifacts/qa-overlay.json"
export MAAS_QA_USAGE_EVIDENCE="$root/artifacts/qa-usage-evidence.json" MAAS_QA_READER_EVIDENCE="$root/artifacts/qa-reader-evidence.json"
export MAAS_TEST_PATTERN='^Test(MySQLUsageAuthority|MySQLProjectionIdentity|ProjectionMissingDoesNotFallback|QAUsageAuthority|QAProjectionIdentity|UsageAuthority)$'
export MAAS_TEST_LOG_NAME=qa-targeted.txt
bash scripts/test-mysql.sh > artifacts/qa-run.log 2>&1