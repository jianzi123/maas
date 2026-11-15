#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
: "${MAAS_TEST_GO_ROOT:?explicit approved Linux Go1.26 required}"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit approved task-cache MySQL8.4.7 required}"
export GOROOT="$MAAS_TEST_GO_ROOT" GOENV=off GOTOOLCHAIN=local GOMAXPROCS="${GOMAXPROCS:-4}"
export GOMODCACHE="${MAAS_TEST_GOMODCACHE:-$root/.cache/mod}" GOCACHE="${MAAS_TEST_GOCACHE:-$root/.cache/build-linux}"
mkdir -p artifacts .cache
"$GOROOT/bin/gofmt" -w test/qa-relay/relay_test.go.in
python3 - <<'PY'
from pathlib import Path
import json
r=Path.cwd()
(r/'artifacts/qa-overlay.json').write_text(json.dumps({'Replace':{str(r/'internal/kernel/qa_relay_test.go'):str(r/'test/qa-relay/relay_test.go.in')}}))
s=(r/'scripts/test-mysql.sh').read_text().replace('./internal/release/mysqlstore ./internal/release/management ./internal/kernel ./internal/controlapi ./cmd/control-api','./internal/kernel')
(r/'.cache/qa-relay-mysql.sh').write_text(s)
PY
export GOFLAGS="-p=4 -overlay=$root/artifacts/qa-overlay.json"
export MAAS_QA_RELAY_EVIDENCE="$root/artifacts/qa-relay-evidence.json" MAAS_D1_SAMPLE_OUTPUT="$root/artifacts/qa-author-relay-source.json"
export MAAS_TEST_PATTERN='^Test(QARelayErrorAndSampling|QASamplerLimits|MySQLRelaySampling|SamplerBoundedDrop)$'
export MAAS_TEST_LOG_NAME=qa-targeted.txt
bash .cache/qa-relay-mysql.sh > artifacts/qa-run.log 2>&1