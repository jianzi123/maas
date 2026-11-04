param([switch]$Integration)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$env:GOPATH = Join-Path $taskRoot '.cache/gopath'
$env:GOMODCACHE = Join-Path $taskRoot '.cache/mod'
$env:GOCACHE = Join-Path $taskRoot '.cache/build'
$env:GOTOOLCHAIN = 'go1.26.0'
if ($Integration) {
    if (-not $env:KUBEBUILDER_ASSETS) { throw 'KUBEBUILDER_ASSETS must point to authorized temporary envtest binaries.' }
    go test -tags envtest ./test/integration -count=1 -v
} else {
    go test ./... -count=1
}
exit $LASTEXITCODE
