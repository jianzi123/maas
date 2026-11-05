#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$task_root"
mkdir -p artifacts
python3 - <<'PY'
import json, pathlib
root=pathlib.Path.cwd()
target=root/'internal/kernel/qa_acceptance_test.go'
source=root/'test/acceptance/kernel_cases_test.go.in'
(root/'artifacts/qa-overlay.json').write_text(json.dumps({'Replace':{str(target):str(source)}}))
PY
chmod u+x .cache/mysql-test/mysql-*/bin/mysqld .cache/mysql-test/mysql-*/bin/mysqladmin .cache/redis-test/root/usr/bin/redis-server
export GOFLAGS="-overlay=$task_root/artifacts/qa-overlay.json"
export MAAS_TEST_PATTERN="${MAAS_TEST_PATTERN:-.}"
bash scripts/test-controlled.sh
