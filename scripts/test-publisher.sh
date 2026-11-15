#!/usr/bin/env bash
# Owned socket-only MySQL; portable binaries/libraries are read-only inputs.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"
: "${MAAS_TEST_MYSQL_BASEDIR:?explicit approved portable MySQL directory required}"
: "${MAAS_TEST_MYSQL_LIB:?explicit portable MySQL library directory required}"
test -x "$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld"
test -x "$repo/artifacts/publisher-linux.test"
mkdir -p artifacts
temporary_dir="$(mktemp -d /tmp/maas11-mysql.XXXXXX)"
mysql_pid=''
cleanup() {
    if [[ -n "$mysql_pid" ]]; then
        if [[ -r "/proc/$mysql_pid/cmdline" ]] && tr '\0' '\n' < "/proc/$mysql_pid/cmdline" | grep -Fqx -- "--datadir=$temporary_dir/data"; then
            kill -TERM "$mysql_pid" 2>/dev/null || true
        fi
        wait "$mysql_pid" || true
    fi
    [[ ! -f "$temporary_dir/mysql.log" ]] || cp -- "$temporary_dir/mysql.log" "$repo/artifacts/publisher-mysql-server.log"
    resolved="$(realpath -- "$temporary_dir")"
    case "$resolved" in /tmp/maas11-mysql.??????) rm -rf -- "$resolved";; *) echo 'Refusing cleanup outside owned directory' >&2; exit 1;; esac
    printf 'owned publisher MySQL stopped; data directory removed\n'
}
trap cleanup EXIT
export LD_LIBRARY_PATH="$MAAS_TEST_MYSQL_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld" --no-defaults --initialize-insecure --user="$(id -un)" --basedir="$MAAS_TEST_MYSQL_BASEDIR" --datadir="$temporary_dir/data" --log-error="$temporary_dir/mysql.log"
"$MAAS_TEST_MYSQL_BASEDIR/bin/mysqld" --no-defaults --user="$(id -un)" --basedir="$MAAS_TEST_MYSQL_BASEDIR" --datadir="$temporary_dir/data" --socket="$temporary_dir/mysql.sock" --pid-file="$temporary_dir/mysql.pid" --skip-networking --mysqlx=OFF --innodb-flush-log-at-trx-commit=1 --sync-binlog=1 --log-error="$temporary_dir/mysql.log" &
mysql_pid=$!
for ((attempt=0; attempt<100; attempt++)); do
    if "$MAAS_TEST_MYSQL_BASEDIR/bin/mysqladmin" --no-defaults --socket="$temporary_dir/mysql.sock" --user=root ping --silent 2>/dev/null; then break; fi
    kill -0 "$mysql_pid" 2>/dev/null || { cat -- "$temporary_dir/mysql.log"; exit 1; }
    sleep 0.1
done
export MAAS_PUBLISHER_TEST_BINARY="$repo/artifacts/publisher-linux"
export MAAS_MYSQL_TEST_SOCKET="$temporary_dir/mysql.sock" MAAS_DISPOSABLE_MYSQL=1
cd -- "$repo/internal/publisher"
"$repo/artifacts/publisher-linux.test" -test.v -test.timeout=90s -test.run '^TestPublisherMySQLService$' | tee "$repo/artifacts/publisher-mysql.txt"
