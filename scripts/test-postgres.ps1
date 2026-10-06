param([string]$Image = 'postgres:16')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the project .venv first.' }
$containerName = 'stock-research-test-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$previousDsn = $env:STOCK_RESEARCH_TEST_DSN
$testExitCode = 1
try {
    $containerId = docker run --detach --rm --name $containerName --label codex.task=financial-phase1 --publish 127.0.0.1::5432 --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=stock_research_test $Image
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated test database.' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker exec $containerName pg_isready -U postgres -d stock_research_test *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Test database did not become ready.' }
    $binding = docker port $containerName 5432
    if ($LASTEXITCODE -ne 0 -or $binding -notmatch '^127\.0\.0\.1:(\d+)$') { throw 'Unexpected test port binding.' }
    $testPort = $Matches[1]
    $env:STOCK_RESEARCH_TEST_DSN = "postgresql://postgres@127.0.0.1:$testPort/stock_research_test?connect_timeout=5"
    Push-Location $projectRoot
    try {
        & $pythonPath -m unittest discover -s tests -v
        $testExitCode = $LASTEXITCODE
    } finally { Pop-Location }
} finally {
    $env:STOCK_RESEARCH_TEST_DSN = $previousDsn
    if ($containerId) {
        docker stop $containerName | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning "Clean up test container manually: $containerName" }
    }
}
exit $testExitCode
