# Run the test suite inside the running Brein container.
#
# Mock-based tests run with no database. Database-backed tests are skipped
# unless BREIN_TEST_DATABASE_URL is set, which this script does by pointing at
# a separate `brein_test` database on the compose Postgres service — never the
# app's own database, because init_db() issues DDL.
#
# Usage:
#   .\scripts\run-tests.ps1                  # whole suite
#   .\scripts\run-tests.ps1 tests/test_x.py  # one file

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$dbContainer = "brein-postgres-1"

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "brein" }
$pgPassword = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "password" }

# Create the test database if it does not exist yet. `createdb` exits non-zero
# when it already exists, which is fine.
docker exec $dbContainer sh -c "createdb -U $pgUser brein_test" 2>$null | Out-Null

$testDbUrl = "postgresql+asyncpg://${pgUser}:${pgPassword}@postgres:5432/brein_test"

if (-not $PytestArgs) {
    $PytestArgs = @("tests/")
}

# A one-off container with the repo bind-mounted: tests/ is in .dockerignore,
# so `docker exec` into the running container cannot see them.
#
# `python -m pytest`, never bare `pytest`: the module form resolves `brein.*`
# against /app rather than a stale copy in site-packages.
docker compose run --rm --no-deps `
    -v "${repoRoot}:/app" `
    -e BREIN_TEST_DATABASE_URL=$testDbUrl `
    -e DATABASE_URL=$testDbUrl `
    -e BREIN_LOG_DIR=/tmp/brein-test-logs `
    brein python -m pytest @PytestArgs

exit $LASTEXITCODE
