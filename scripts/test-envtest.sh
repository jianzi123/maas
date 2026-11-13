#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
export GOROOT="$task_root/.cache/mod/golang.org/toolchain@v0.0.1-go1.26.0.linux-amd64"
export GOPATH="$task_root/.cache/gopath-linux"
export GOMODCACHE="$task_root/.cache/mod"
export GOCACHE="$task_root/.cache/build-linux"
export GOENV=off
export GOTOOLCHAIN=local
export KUBEBUILDER_ASSETS="$task_root/.cache/envtest/k8s/1.36.0-linux-amd64"
for binary in "$GOROOT/bin/go" "$KUBEBUILDER_ASSETS/kube-apiserver" "$KUBEBUILDER_ASSETS/etcd"; do
    test -f "$binary" || { echo "Missing temporary test dependency: $binary" >&2; exit 1; }
done
chmod u+x "$GOROOT"/bin/* "$GOROOT"/pkg/tool/linux_amd64/* "$KUBEBUILDER_ASSETS"/*
"$GOROOT/bin/go" test -tags envtest ./test/integration -count=1 -v
