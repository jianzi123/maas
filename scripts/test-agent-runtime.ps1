$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$env:GOCACHE = Join-Path $repo '.cache/build'
$evidence = Join-Path $repo 'artifacts/agent-runtime'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
go test -json ./internal/agentruntime/... -count=1 -timeout=90s | Tee-Object -FilePath (Join-Path $evidence 'tests.jsonl')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
go vet ./internal/agentruntime/... ./internal/kernel
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
go test -json ./internal/kernel -run '^TestMySQLAgentChildrenUseOneLedger$' -count=1 -timeout=90s | Tee-Object -FilePath (Join-Path $evidence 'mysql.jsonl')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
go run -tags agentcontrolled ./cmd/agent-headless --state-dir (Join-Path $repo '.cache/agent-headless-evidence') | Tee-Object -FilePath (Join-Path $evidence 'headless.jsonl')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Evidence saved to $evidence. MySQL SKIP is not a passing database result."
