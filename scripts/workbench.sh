#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"
bash scripts/setup-workbench.sh
export GOROOT="$repo/.cache/go-linux/go" GOMODCACHE="$repo/.cache/mod" GOCACHE="$repo/.cache/build-linux" GOPATH="$repo/.cache/gopath-linux" GOTOOLCHAIN=local GOENV=off
export KUBEBUILDER_ASSETS="$repo/.cache/envtest/controller-tools/envtest"
mysql_base="$repo/.cache/mysql-test/mysql-8.4.7-linux-glibc2.28-x86_64-minimal"
export LD_LIBRARY_PATH="$repo/.cache/mysql-test/lib/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p .cache/bin artifacts/workbench
echo 'Building the integrated Go workbench…' >&2
"$GOROOT/bin/go" build -tags localworkbench -o .cache/bin/maas-workbench ./cmd/workbench
temporary_dir="$(mktemp -d /tmp/maas-workbench.XXXXXX)"
mysql_pid=''
cleanup(){
 if [[ -n "$mysql_pid" ]]; then
  if [[ -r "/proc/$mysql_pid/cmdline" ]] && tr '\0' '\n' <"/proc/$mysql_pid/cmdline" | grep -Fqx -- "--datadir=$temporary_dir/data"; then kill -TERM "$mysql_pid" 2>/dev/null || true; fi
  wait "$mysql_pid" || true
 fi
 [[ ! -f "$temporary_dir/mysql.log" ]] || cp -- "$temporary_dir/mysql.log" "$repo/artifacts/workbench/mysql.log"
 local resolved="$(realpath -- "$temporary_dir")"
 case "$resolved" in /tmp/maas-workbench.??????) rm -rf -- "$resolved";; *) echo 'Refusing unexpected cleanup path' >&2; exit 1;; esac
 echo '{"event":"stopped","cleaned":true}'
}
trap cleanup EXIT
"$mysql_base/bin/mysqld" --no-defaults --initialize-insecure --user="$(id -un)" --basedir="$mysql_base" --datadir="$temporary_dir/data" --log-error="$temporary_dir/mysql.log"
"$mysql_base/bin/mysqld" --no-defaults --user="$(id -un)" --basedir="$mysql_base" --datadir="$temporary_dir/data" --socket="$temporary_dir/mysql.sock" --pid-file="$temporary_dir/mysql.pid" --skip-networking --mysqlx=OFF --innodb-flush-log-at-trx-commit=1 --sync-binlog=1 --log-error="$temporary_dir/mysql.log" &
mysql_pid=$!
for((attempt=0;attempt<150;attempt++));do
 if "$mysql_base/bin/mysqladmin" --no-defaults --socket="$temporary_dir/mysql.sock" --user=root ping --silent >/dev/null 2>&1;then break;fi
 kill -0 "$mysql_pid" 2>/dev/null || { echo 'Temporary MySQL failed to start' >&2;exit 1; }
 sleep .1
done
export MAAS_WORKBENCH_MYSQL_SOCKET="$temporary_dir/mysql.sock"
"$repo/.cache/bin/maas-workbench" -root "$repo" -listen "127.0.0.1:${MAAS_WORKBENCH_PORT:-4179}"
