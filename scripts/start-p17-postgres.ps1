param([string]$Image = '57c72fd2a128')
$ErrorActionPreference = 'Stop'
$containerName = 'stock-research-p17'
$volumeName = 'stock-research-p17-data'
$runtime = Join-Path (Split-Path -Parent $PSScriptRoot) '.runtime'
$dsnFile = Join-Path $runtime 'p17-dsn.txt'

$existing = docker ps -a --filter "name=^/$containerName`$" --format '{{.Names}}'
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Docker containers.' }
if ($existing) {
    if (-not (Test-Path -LiteralPath $dsnFile)) {
        throw 'Existing P1.7 database has no local DSN file; refusing to replace it.'
    }
    docker start $containerName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start existing P1.7 database.' }
} else {
    if (Test-Path -LiteralPath $dsnFile) {
        throw 'P1.7 DSN file exists without its container; refusing to create a mismatched database.'
    }
    [byte[]]$randomBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    $password = [Convert]::ToHexString($randomBytes).ToLowerInvariant()
    docker run --detach --name $containerName --label codex.task=financial-p17 --publish 127.0.0.1::5432 --mount "type=volume,src=$volumeName,dst=/var/lib/postgresql/data" --env "POSTGRES_PASSWORD=$password" --env POSTGRES_DB=stock_research_p17 $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create P1.7 database.' }
}

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    docker exec $containerName pg_isready -U postgres -d stock_research_p17 *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw 'P1.7 database did not become ready.' }

$binding = docker port $containerName 5432
if ($LASTEXITCODE -ne 0 -or $binding -notmatch '^127\.0\.0\.1:(\d+)$') {
    throw 'Unexpected P1.7 database port binding.'
}
$port = $Matches[1]
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if ($existing) {
    # Docker can reassign a randomly published host port after restart.
    $saved = [Uri](Get-Content -LiteralPath $dsnFile -Raw)
    if ($saved.Host -ne '127.0.0.1' -or $saved.AbsolutePath -ne '/stock_research_p17') {
        throw 'Existing P1.7 DSN does not identify the dedicated local database.'
    }
    $dsn = "postgresql://$($saved.UserInfo)@127.0.0.1:$port/stock_research_p17?connect_timeout=5"
} else {
    $dsn = "postgresql://postgres:$password@127.0.0.1:$port/stock_research_p17?connect_timeout=5"
}
Set-Content -LiteralPath $dsnFile -Value $dsn -NoNewline
Write-Output "P1.7 database ready; persistent volume: $volumeName; DSN: .runtime/p17-dsn.txt"
