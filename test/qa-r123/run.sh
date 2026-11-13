#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$task_root"
: "${MAAS_TEST_GO_ROOT:?explicit approved Go required}"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit owned MySQL cache required}"
export GOROOT="$MAAS_TEST_GO_ROOT" GOENV=off GOTOOLCHAIN=local GOMAXPROCS=4
export MAAS_QA_R123_EVIDENCE="$task_root/artifacts/qa-relay-evidence.json"
mkdir -p artifacts .cache
"$GOROOT/bin/gofmt" -w test/qa-r123/*.go.in
python3 - <<'PY'
from pathlib import Path
import json
r=Path.cwd()
(r/'artifacts/qa-overlay.json').write_text(json.dumps({'Replace':{str(r/'internal/kernel/qa_relay_test.go'):str(r/'test/qa-r123/boundary_test.go.in'),str(r/'internal/kernel/qa_r3_test.go'):str(r/'test/qa-r123/publisher_test.go.in')}}))
s=(r/'scripts/test-mysql.sh').read_text().replace('./internal/release/mysqlstore ./internal/release/management ./internal/kernel ./internal/controlapi ./cmd/control-api','./internal/kernel')
(r/'.cache/qa-relay-mysql.sh').write_text(s)
PY
export GOFLAGS="-p=4 -overlay=$task_root/artifacts/qa-overlay.json"

export MAAS_TEST_PATTERN='^Test(MAAS17.*|QAR1R2|QAR1TransactionRollback|QAR3PublisherProjection)$'
export MAAS_TEST_LOG_NAME=qa-targeted.txt
bash .cache/qa-relay-mysql.sh > artifacts/qa-run.log 2>&1