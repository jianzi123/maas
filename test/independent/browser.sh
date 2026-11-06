#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
: "${MAAS_TEST_GO_ROOT:?explicit Go1.26 required}"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit approved MySQL cache required}"
: "${MAAS_TEST_REDIS_BASEDIR:?explicit approved Redis cache required}"
: "${KUBEBUILDER_ASSETS:?explicit envtest1.36 assets required}"
: "${MAAS_FE_NODE:?WSL-visible Windows Node executable required}"
: "${MAAS_FE_CONSOLE_DIR:?WSL-visible exact aef53ee console directory required}"
: "${MAAS_FE_CONSOLE_NODE_DIR:?Windows-visible console directory required}"
created_script=0
script="$MAAS_FE_CONSOLE_DIR/scripts/qa-release-browser.mjs"
if [[ -e "$script" ]]; then cmp "$script" test/independent/release-browser.mjs; else cp test/independent/release-browser.mjs "$script"; created_script=1; fi
cleanup(){ if [[ "$created_script" == 1 ]]; then rm -- "$script"; fi; }
trap cleanup EXIT
mkdir -p artifacts .cache
python3 - <<'PY'
from pathlib import Path
import json
r=Path.cwd()
(r/'artifacts/qa-browser-overlay.json').write_text(json.dumps({'Replace':{str(r/'test/integration/frontend_browser_test.go'):str(r/'test/independent/frontend_browser_test.go.in')}}))
p=(r/'scripts/test-mysql.sh').read_text().replace("-run '^TestManagement'","-run '^TestManagementFrontendBrowser$'").replace('artifacts/release-management-envtest.txt','artifacts/qa-browser-go.txt')
(r/'.cache/qa-browser-mysql.sh').write_text(p)
PY
export MAAS_TEST_ENVTEST=1 MAAS_TEST_PATTERN='^$' MAAS_TEST_LOG_NAME=qa-browser-prerequisites.txt
export GOFLAGS="-overlay=$root/artifacts/qa-browser-overlay.json"
bash .cache/qa-browser-mysql.sh > artifacts/qa-browser-run.log 2>&1