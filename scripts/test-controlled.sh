#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
export MAAS_TEST_MYSQL_BASEDIR="$task_root/.cache/mysql-test/mysql-8.4.7-linux-glibc2.28-x86_64-minimal"
export MAAS_TEST_GO_ROOT="$task_root/.cache/go-linux/go"
export MAAS_TEST_REDIS_BASEDIR="$task_root/.cache/redis-test/root"
exec bash scripts/test-mysql.sh
