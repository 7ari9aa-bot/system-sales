<#
.SYNOPSIS
    Run the backend test suite against the LOCAL Postgres + Redis on this machine.

.DESCRIPTION
    Why this exists: the repository's backend/.env points at PRODUCTION Supabase,
    whose pooler is slow and flaky from here (a 25-test file took 4 minutes and
    every database test errored on DNS). This machine already carries a local
    Postgres 17 + pgvector and a Redis under C:\pg-kasher; this script points
    the suite at them.

    Every test runs inside a transaction that is rolled back, so local data is
    never changed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File backend/scripts/dev/local_test.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File backend/scripts/dev/local_test.ps1 tests/test_inventory_service.py -k stocktake
#>
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = 'Stop'
$backend = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$kasher = Join-Path $backend '.env.kasher'

if (-not (Test-Path $kasher)) {
    throw "backend/.env.kasher is missing - it holds the local DSNs."
}

Get-Content $kasher | ForEach-Object {
    if ($_ -match '^([A-Z_]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), 'Process')
    }
}

$env:ENVIRONMENT = 'local'
$env:PYTHONDONTWRITEBYTECODE = '1'
# The suite is hermetic: it must not read backend/.env (that points at production).
Remove-Item Env:\PYTEST_ALLOW_DOTENV -ErrorAction SilentlyContinue

Push-Location $backend
try {
    $invocation = @('-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--no-header')
    if ($PytestArgs) { $invocation += $PytestArgs }
    & (Join-Path $backend '.venv\Scripts\python.exe') @invocation
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
