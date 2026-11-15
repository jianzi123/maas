#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
: "${MAAS_TEST_GO_ROOT:?explicit approved Go1.26 root required}"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit approved MySQL test cache required}"
: "${MAAS_TEST_REDIS_BASEDIR:?explicit approved Redis test cache required}"
: "${KUBEBUILDER_ASSETS:?explicit envtest1.36 assets required}"
export MAAS_TEST_ENVTEST=1
mkdir -p artifacts .cache
if [[ "${MAAS_QA_PHASE:-all}" == all ]]; then
  export MAAS_TEST_LOG_NAME=qa-baseline-shared.txt
  export MAAS_MANAGEMENT_HTTP_EVIDENCE="$root/artifacts/qa-baseline-http.json"
  bash scripts/test-mysql.sh > artifacts/qa-baseline-run.log 2>&1
  cp artifacts/release-management-envtest.txt artifacts/qa-baseline-management.txt
fi
python3 - <<'PY'
import json
from pathlib import Path
r=Path.cwd()
(r/'artifacts/qa-overlay.json').write_text(json.dumps({'Replace':{
str(r/'test/integration/management_test.go'):str(r/'test/independent/management_test.go.in'),
str(r/'internal/kernel/qa_acceptance_test.go'):str(r/'test/independent/kernel_cases_test.go.in')
}}))
p=(r/'scripts/test-mysql.sh').read_text()
p=p.replace("-run '^TestManagement'", "-run '^TestQAIndependentManagement$'")
p=p.replace('artifacts/release-management-envtest.txt','artifacts/qa-independent-management.txt')
(r/'.cache/qa-mysql-local.sh').write_text(p)
PY
export GOFLAGS="-overlay=$root/artifacts/qa-overlay.json"
export MAAS_TEST_PATTERN='^TestQATerminationMatrix$/^before_headers$/^transport_eof$'
export MAAS_TEST_LOG_NAME=qa-eof.txt
export MAAS_MANAGEMENT_HTTP_EVIDENCE="$root/artifacts/qa-independent-http.json"
bash .cache/qa-mysql-local.sh > artifacts/qa-independent-run.log 2>&1