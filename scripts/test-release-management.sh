#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
export MAAS_TEST_ENVTEST=1
export MAAS_TEST_LOG_NAME="${MAAS_TEST_LOG_NAME:-release-management-mysql.txt}"
export KUBEBUILDER_ASSETS="$task_root/.cache/envtest/controller-tools/envtest"
export MAAS_MANAGEMENT_HTTP_EVIDENCE="$task_root/artifacts/release-management-http.json"
test -f "$KUBEBUILDER_ASSETS/kube-apiserver"
chmod u+x "$KUBEBUILDER_ASSETS"/*
exec bash scripts/test-controlled.sh
