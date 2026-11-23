#!/usr/bin/env bash
set -euo pipefail
export GOMAXPROCS="${GOMAXPROCS:-2}"
export GOFLAGS="${GOFLAGS:--p=2 -buildvcs=false}"
export MAAS_TEST_PRODUCT_SERVICE=1
export MAAS_TEST_LOG_NAME=product-service-mysql.jsonl
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/test-mysql.sh"
