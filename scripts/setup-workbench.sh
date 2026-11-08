#!/usr/bin/env bash
# Fixed local development tools; no system installation or target cluster.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Local workbench needs Linux amd64 (Windows: Ubuntu WSL2).' >&2; exit 1; }
mkdir -p "$repo/.cache/go-linux" "$repo/.cache/mysql-test" "$repo/.cache/envtest"
download(){
 local url="$1" output="$2" algorithm="$3" digest="$4"
 if [[ ! -f "$output" ]]; then
   echo "Downloading pinned $(basename -- "$output")" >&2
   curl --fail --silent --show-error --location --retry 2 --connect-timeout 20 "$url" -o "$output.partial"
   mv -- "$output.partial" "$output"
 fi
 printf '%s  %s\n' "$digest" "$output" | "${algorithm}sum" --check --status || { echo "Checksum mismatch: $(basename -- "$output")" >&2; exit 1; }
}
if [[ ! -x "$repo/.cache/go-linux/go/bin/go" ]]; then
 download https://go.dev/dl/go1.26.0.linux-amd64.tar.gz "$repo/.cache/go-linux/go.tar.gz" sha256 aac1b08a0fb0c4e0a7c1555beb7b59180b05dfc5a3d62e40e9de90cd42f88235
 tar -xzf "$repo/.cache/go-linux/go.tar.gz" -C "$repo/.cache/go-linux"
fi
if [[ ! -f "$repo/.cache/mysql-test/mysql-8.4.7-linux-glibc2.28-x86_64-minimal/bin/mysqld" ]]; then
 download https://cdn.mysql.com/archives/mysql-8.4/mysql-8.4.7-linux-glibc2.28-x86_64-minimal.tar.xz "$repo/.cache/mysql-test/mysql.tar.xz" sha256 543ec7d310c4f0786344d243663e5db9e985b03e741ee935370ab08b3274f05a
 tar -xJf "$repo/.cache/mysql-test/mysql.tar.xz" -C "$repo/.cache/mysql-test"
fi
if [[ ! -f "$repo/.cache/mysql-test/lib/usr/lib/x86_64-linux-gnu/libaio.so.1" ]]; then
 download https://archive.ubuntu.com/ubuntu/pool/main/liba/libaio/libaio1_0.3.112-13build1_amd64.deb "$repo/.cache/mysql-test/libaio1_0.3.112-13build1_amd64.deb" sha256 2dcfe0b49d7cccfbf1bd6a3f627cf44bea9f51fb32f7e0e552a0df75698e0d27
 dpkg-deb -x "$repo/.cache/mysql-test/libaio1_0.3.112-13build1_amd64.deb" "$repo/.cache/mysql-test/lib"
fi
if [[ ! -f "$repo/.cache/envtest/controller-tools/envtest/kube-apiserver" ]]; then
 download https://github.com/kubernetes-sigs/controller-tools/releases/download/envtest-v1.36.0/envtest-v1.36.0-linux-amd64.tar.gz "$repo/.cache/envtest/envtest-v1.36.0-linux-amd64.tar.gz" sha512 302d6a4c3b7d79b8a6168cd9fd5f18e718048211d25012d969d320e06b39672d17338bcd008c29adf98b41048a6f7d80c90ab0165b4b861497ef74c7bc6c1531
 tar -xzf "$repo/.cache/envtest/envtest-v1.36.0-linux-amd64.tar.gz" -C "$repo/.cache/envtest"
fi
chmod u+x "$repo/.cache/go-linux/go"/bin/* "$repo/.cache/go-linux/go"/pkg/tool/linux_amd64/* "$repo/.cache/envtest/controller-tools/envtest"/*
