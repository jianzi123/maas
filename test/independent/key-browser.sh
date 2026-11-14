#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
: "${MAAS_TEST_GO_ROOT:?explicit approved Go root required}"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit approved MySQL cache required}"
: "${MAAS_TEST_REDIS_BASEDIR:?explicit approved Redis cache required}"
: "${MAAS_FE_NODE:?explicit Node executable required}"
: "${MAAS_FE_CONSOLE_DIR:?fixed aef53ee console path required}"
: "${MAAS_FE_CONSOLE_NODE_DIR:?Windows console path required}"
mkdir -p artifacts .cache
python3 - <<'PY'
from pathlib import Path
import json
r=Path.cwd()
(r/'artifacts/qa-key-browser-overlay.json').write_text(json.dumps({'Replace':{str(r/'internal/controlapi/qa_key_browser_test.go'):str(r/'test/independent/key_browser_test.go.in')}}))
PY
export GOFLAGS="-overlay=$root/artifacts/qa-key-browser-overlay.json"
export MAAS_TEST_PATTERN='^TestFrontendBrowser$'
export MAAS_TEST_LOG_NAME=qa-key-browser.txt
unset MAAS_TEST_ENVTEST
bash scripts/test-mysql.sh > artifacts/qa-key-browser-run.log 2>&1
