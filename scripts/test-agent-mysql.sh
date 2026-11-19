#!/usr/bin/env bash
# Reuses the existing owned disposable server lifecycle and pinned tool inputs.
set -euo pipefail
export MAAS_TEST_AGENT_RUNTIME=1
export MAAS_TEST_LOG_NAME=agent-runtime-mysql.jsonl
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/test-mysql.sh"
