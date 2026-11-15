#!/usr/bin/env bash
# Foreground test orchestration: only its own PID/data/socket are created.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
: "${MAAS_TEST_MYSQL_BASEDIR:?Set to the approved portable MySQL directory}"
: "${MAAS_TEST_GO_ROOT:?Set to the approved Linux Go toolchain directory}"
case "$MAAS_TEST_MYSQL_BASEDIR" in "$task_root"/.cache/*) ;; *) echo 'MySQL binaries must be in the task cache' >&2; exit 1;; esac
export GOROOT="$MAAS_TEST_GO_ROOT"
export GOPATH="$task_root/.cache/gopath-linux"
export GOMODCACHE="${MAAS_TEST_GOMODCACHE:-$task_root/.cache/mod}"
export GOCACHE="${MAAS_TEST_GOCACHE:-$task_root/.cache/build-linux}"
export GOTOOLCHAIN=local
export GOENV=off
chmod u+x "$GOROOT"/bin/* "$GOROOT"/pkg/tool/linux_amd64/*
temporary_dir="$(mktemp -d /tmp/maas11-mysql.XXXXXX)"
mysql_pid=''
redis_pid=''
cleanup() {
    if [[ -n "$redis_pid" ]]; then
        # Redis rewrites argv to "redis-server *:0". Verify the exact recorded
        # child's executable and parent instead of searching its new title.
        if [[ "$(readlink -f "/proc/$redis_pid/exe" 2>/dev/null)" == "$(realpath -- "$MAAS_TEST_REDIS_BASEDIR/usr/bin/redis-server")" ]] && [[ "$(ps -o ppid= -p "$redis_pid" | tr -d ' ')" == "$$" ]]; then
            kill -TERM "$redis_pid" 2>/dev/null || true
        fi
        wait "$redis_pid" || true
    fi
    if [[ -n "$mysql_pid" ]]; then
        if [[ -r "/proc/$mysql_pid/cmdline" ]] && tr '\0' '\n' < "/proc/$mysql_pid/cmdline" | grep -Fqx -- "--datadir=$temporary_dir/data"; then
            kill -TERM "$mysql_pid" 2>/dev/null || true
        fi
        wait "$mysql_pid" || true
    fi
    mkdir -p "$task_root/artifacts"
    if [[ -f "$temporary_dir/mysql.log" ]]; then cp -- "$temporary_dir/mysql.log" "$task_root/artifacts/mysql-test-server.log"; fi
    resolved_temporary_dir="$(realpath -- "$temporary_dir")"
    case "$resolved_temporary_dir" in /tmp/maas11-mysql.??????) rm -rf -- "$resolved_temporary_dir";; *) echo 'Refusing cleanup outside owned test directory' >&2;; esac
}
trap cleanup EXIT
export LD_LIBRARY_PATH="$task_root/.cache/mysql-test/lib/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld" --no-defaults --initialize-insecure --user="$(id -un)" --basedir="$MAAS_TEST_MYSQL_BASEDIR" --datadir="$temporary_dir/data" --log-error="$temporary_dir/mysql.log"
"$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld" --no-defaults --user="$(id -un)" --basedir="$MAAS_TEST_MYSQL_BASEDIR" --datadir="$temporary_dir/data" --socket="$temporary_dir/mysql.sock" --pid-file="$temporary_dir/mysql.pid" --skip-networking --mysqlx=OFF --innodb-flush-log-at-trx-commit=1 --sync-binlog=1 --log-error="$temporary_dir/mysql.log" &
mysql_pid=$!
printf 'temporary MySQL PID=%s; logs=%s/mysql.log\n' "$mysql_pid" "$temporary_dir"
for ((attempt=0; attempt<100; attempt++)); do
    if "$MAAS_TEST_MYSQL_BASEDIR/bin/mysqladmin" --no-defaults --socket="$temporary_dir/mysql.sock" --user=root ping --silent 2>/dev/null; then break; fi
    kill -0 "$mysql_pid" 2>/dev/null || { cat -- "$temporary_dir/mysql.log"; exit 1; }
    sleep 0.1
done
export MAAS_MYSQL_TEST_SOCKET="$temporary_dir/mysql.sock"
export MAAS_DISPOSABLE_MYSQL=1
if [[ -n "${MAAS_TEST_REDIS_BASEDIR:-}" ]]; then
    case "$MAAS_TEST_REDIS_BASEDIR" in "$task_root"/.cache/*) ;; *) echo 'Redis must be in task cache' >&2; exit 1;; esac
    export LD_LIBRARY_PATH="$MAAS_TEST_REDIS_BASEDIR/usr/lib/x86_64-linux-gnu:$MAAS_TEST_REDIS_BASEDIR/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
    "$MAAS_TEST_REDIS_BASEDIR/usr/bin/redis-server" --port 0 --unixsocket "$temporary_dir/redis.sock" --unixsocketperm 700 --save '' --appendonly no --daemonize no --dir "$temporary_dir" --logfile "$temporary_dir/redis.log" &
    redis_pid=$!
    for ((attempt=0; attempt<100; attempt++)); do
        if [[ -S "$temporary_dir/redis.sock" ]]; then break; fi
        kill -0 "$redis_pid" 2>/dev/null || { cat -- "$temporary_dir/redis.log"; exit 1; }
        sleep 0.1
    done
    export MAAS_REDIS_TEST_SOCKET="$temporary_dir/redis.sock"
fi
mkdir -p "$task_root/artifacts"
test_log="${MAAS_TEST_LOG_NAME:-mysql-tests.txt}"
[[ "$test_log" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo 'Invalid test log name' >&2; exit 1; }
if [[ "${MAAS_TEST_WORKBENCH_IDENTITY:-}" == 1 ]]; then
    "$GOROOT/bin/go" test -tags localworkbench ./cmd/workbench -count=1 -v -timeout=120s -run '^TestLocalRuntimeIdentities$' | tee "$task_root/artifacts/$test_log"
else
    "$GOROOT/bin/go" test ./internal/release/mysqlstore ./internal/release/management ./internal/kernel ./internal/controlapi ./cmd/control-api -count=1 -v -timeout=180s -run "${MAAS_TEST_PATTERN:-.}" | tee "$task_root/artifacts/$test_log"
fi
if [[ "${MAAS_TEST_ENVTEST:-}" == 1 ]]; then
    "$GOROOT/bin/go" test -tags envtest ./test/integration -count=1 -v -timeout=150s -run '^TestManagement' | tee "$task_root/artifacts/release-management-envtest.txt"
fi
