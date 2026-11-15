#!/usr/bin/env bash
# R5 only: reuse approved portable tools as read-only inputs; own all state.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
: "${MAAS_R5_TOOL_ROOT:?Path to existing approved task cache}"
export GOROOT="$MAAS_R5_TOOL_ROOT/go-linux/go"
export GOTOOLCHAIN=local GOENV=off
export GOPROXY=off
mkdir -p "$task_root/.cache/r5" "$task_root/artifacts"
export LD_LIBRARY_PATH="$MAAS_R5_TOOL_ROOT/mysql-test/lib/usr/lib/x86_64-linux-gnu"
mysql_base="$MAAS_R5_TOOL_ROOT/mysql-test/mysql-8.4.7-linux-glibc2.28-x86_64-minimal"
owned="$(mktemp -d /tmp/maas11-mysql.XXXXXX)"
mysql_pid=''
cleanup() {
    if [[ -n "$mysql_pid" ]]; then
        if [[ -r "/proc/$mysql_pid/cmdline" ]] && tr '\0' '\n' < "/proc/$mysql_pid/cmdline" | grep -Fqx -- "--datadir=$owned/data"; then kill -TERM "$mysql_pid" 2>/dev/null || true; fi
        wait "$mysql_pid" || true
    fi
    cp -- "$owned/mysql.log" "$task_root/artifacts/r5-mysql-server.log" 2>/dev/null || true
    case "$(realpath -- "$owned")" in /tmp/maas11-mysql.??????) rm -rf -- "$owned";; *) exit 1;; esac
    printf 'owned_mysql_and_data_cleaned=true\n'
}
trap cleanup EXIT
export GOPATH="$owned/gopath" GOMODCACHE="$owned/mod" GOCACHE="$owned/build"
mkdir -p "$GOMODCACHE"
# Avoid copying unrelated downloaded Go toolchains and zip archives. Copy the
# extracted modules plus download metadata to a Linux filesystem owned by us.
tar -C "$MAAS_R5_TOOL_ROOT/mod" --exclude='golang.org/toolchain*' --exclude='cache/download/golang.org/toolchain' --exclude='*.zip' -cf - . | tar -C "$GOMODCACHE" -xf -
printf 'owned_dependencies_ready=true\n'
"$mysql_base/bin/mysqld" --no-defaults --initialize-insecure --user="$(id -un)" --basedir="$mysql_base" --datadir="$owned/data" --log-error="$owned/mysql.log"
"$mysql_base/bin/mysqld" --no-defaults --user="$(id -un)" --basedir="$mysql_base" --datadir="$owned/data" --socket="$owned/mysql.sock" --skip-networking --mysqlx=OFF --log-error="$owned/mysql.log" &
mysql_pid=$!
for ((i=0;i<100;i++)); do
    if "$mysql_base/bin/mysqladmin" --no-defaults --socket="$owned/mysql.sock" --user=root ping --silent 2>/dev/null; then break; fi
    kill -0 "$mysql_pid" 2>/dev/null || { cat "$owned/mysql.log"; exit 1; }
    sleep 0.1
done
export MAAS_MYSQL_TEST_SOCKET="$owned/mysql.sock" MAAS_DISPOSABLE_MYSQL=1
export KUBEBUILDER_ASSETS="$MAAS_R5_TOOL_ROOT/envtest/controller-tools/envtest"
export MAAS_MANAGEMENT_HTTP_EVIDENCE="$task_root/artifacts/r5-http.json"
cd -- "$task_root"
"$GOROOT/bin/go" version
"$mysql_base/bin/mysqld" --version
"$GOROOT/bin/gofmt" -w internal/release/history/spec.go internal/release/history/kubernetes.go internal/release/management/service.go test/integration/management_test.go
"$GOROOT/bin/go" test -tags envtest ./test/integration -count=1 -v -timeout=180s -run '^TestManagementHTTPLifecycle$/(create-list-detail-and-exact-operation|R5-history-rejections)$' | tee "$task_root/artifacts/r5-targeted.txt"
"$GOROOT/bin/go" test ./internal/release/history ./internal/release/management ./internal/controlapi -count=1 | tee "$task_root/artifacts/r5-unit.txt"
"$GOROOT/bin/go" vet ./internal/release/history ./internal/release/management ./internal/controlapi
"$GOROOT/bin/go" build ./cmd/control-api ./cmd/operator
