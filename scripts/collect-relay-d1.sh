#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"
mkdir -p artifacts
export MAAS_D1_SAMPLE_OUTPUT="$repo/artifacts/go-relay-d1.json"
export MAAS_TEST_PATTERN=TestMySQLRelaySampling
export MAAS_TEST_LOG_NAME=go-relay-d1-tests.txt
bash scripts/test-controlled.sh
python3 scripts/relay-d1-manifest.py
