#!/usr/bin/env bash
# Run only against a disposable backend checkout and binaries approved by the operator.
set -euo pipefail
frontend="$(cd -- "$(dirname -- "$0")/.." && pwd)"
: "${MAAS_GO_SOURCE:?Set an isolated backend checkout (821269b baseline)}"
: "${MAAS_TEST_MYSQL_BASEDIR:?Set portable MySQL basedir}"
: "${MAAS_TEST_GO_ROOT:?Set Linux Go 1.26 basedir}"
: "${KUBEBUILDER_ASSETS:?Set envtest 1.36 binary directory}"
: "${MAAS_FE_NODE:?Set the Node executable}"
backend="$(cd -- "$MAAS_GO_SOURCE" && pwd)"
for file in internal/controlapi/frontend_http_test.go internal/controlapi/frontend_browser_test.go test/integration/frontend_management_test.go test/integration/frontend_workspace_test.go; do
 test ! -e "$backend/$file" || { echo "Refuse to overwrite existing test file: $file" >&2; exit 2; }
done
export GOROOT="$MAAS_TEST_GO_ROOT" GOPATH="$backend/.cache/gopath-linux" GOMODCACHE="$backend/.cache/mod" GOCACHE="$backend/.cache/build-linux" GOTOOLCHAIN=local GOENV=off GOMAXPROCS=3
export MAAS_FE_CONSOLE_DIR="$frontend"
export MAAS_FE_CONSOLE_NODE_DIR="${MAAS_FE_CONSOLE_NODE_DIR:-$frontend}"
export LD_LIBRARY_PATH="$backend/.cache/mysql-test/lib/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
temporary_dir="$(mktemp -d /tmp/maas11-mysql.XXXXXX)"
mysql_pid=''
cleanup(){
 if [[ -n "$mysql_pid" ]]; then
   if [[ -r "/proc/$mysql_pid/cmdline" ]] && tr '\0' '\n' <"/proc/$mysql_pid/cmdline" | grep -Fqx -- "--datadir=$temporary_dir/data"; then kill -TERM "$mysql_pid" 2>/dev/null || true; fi
   wait "$mysql_pid" || true
 fi
 rm -f -- "$backend/internal/controlapi/frontend_http_test.go" "$backend/internal/controlapi/frontend_browser_test.go" "$backend/test/integration/frontend_management_test.go" "$backend/test/integration/frontend_workspace_test.go"
 local resolved="$(realpath -- "$temporary_dir")"
 case "$resolved" in /tmp/maas11-mysql.??????) rm -rf -- "$resolved";; *) echo 'Refuse unexpected temporary directory' >&2; exit 1;; esac
}
trap cleanup EXIT
cp -- "$frontend/scripts/http-harness.go.txt" "$backend/internal/controlapi/frontend_http_test.go"
cp -- "$frontend/scripts/go-browser-harness.go.txt" "$backend/internal/controlapi/frontend_browser_test.go"
cp -- "$frontend/scripts/management-harness.go.txt" "$backend/test/integration/frontend_workspace_test.go"
cp -- "$frontend/scripts/release-browser-harness.go.txt" "$backend/test/integration/frontend_management_test.go"
"$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld" --no-defaults --initialize-insecure --user="$(id -un)" --basedir="$MAAS_TEST_MYSQL_BASEDIR" --datadir="$temporary_dir/data" --log-error="$temporary_dir/mysql.log"
"$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld" --no-defaults --user="$(id -un)" --basedir="$MAAS_TEST_MYSQL_BASEDIR" --datadir="$temporary_dir/data" --socket="$temporary_dir/mysql.sock" --pid-file="$temporary_dir/mysql.pid" --skip-networking --mysqlx=OFF --log-error="$temporary_dir/mysql.log" &
mysql_pid=$!
for((attempt=0;attempt<100;attempt++)); do
 if "$MAAS_TEST_MYSQL_BASEDIR/bin/mysqladmin" --no-defaults --socket="$temporary_dir/mysql.sock" --user=root ping --silent 2>/dev/null; then break; fi
 kill -0 "$mysql_pid" || { cat "$temporary_dir/mysql.log";exit 1; }
 sleep .1
done
export MAAS_MYSQL_TEST_SOCKET="$temporary_dir/mysql.sock" MAAS_DISPOSABLE_MYSQL=1
cd -- "$backend"
mkdir -p "$frontend/artifacts"
"$GOROOT/bin/go" test ./internal/controlapi -run '^TestFrontend' -count=1 -v -timeout=100s | tee "$frontend/artifacts/go-key-http.log"
"$GOROOT/bin/go" test -tags envtest ./test/integration -run "^Test(ManagementFrontendBrowser|WorkspaceFrontendBrowser)$" -count=1 -v -timeout=150s | tee "$frontend/artifacts/management-http.log"
