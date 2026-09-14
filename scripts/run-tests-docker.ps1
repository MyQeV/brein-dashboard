<#
.SYNOPSIS
    Run the test suite inside the app image, against the compose Postgres.

.DESCRIPTION
    The suite needs two things the plain `pytest` invocation does not give it:

      * a database it may create and drop tables in — hence brein_test, made
        here if it does not exist;
      * DATABASE_URL pointing at the compose network rather than at whatever
        the developer's .env holds. tests/conftest.py only *defaults* that
        variable, so an inherited localhost URL wins and every database-backed
        test fails with a connection error.

    Tests that need a database opt in via BREIN_TEST_DATABASE_URL; without it
    they skip, so both variables are set.

.EXAMPLE
    ./scripts/run-tests-docker.ps1
    ./scripts/run-tests-docker.ps1 -Path tests/test_security.py -Extra "-x"
    ./scripts/run-tests-docker.ps1 -MountSource
    ./scripts/run-tests-docker.ps1 -Repo C:\tmp\exported-tree -MountSource
#>
param(
    [string]$Path = "tests/",
    [string]$Extra = "",
    [string]$Project = "brein",
    [string]$DbUser = $(if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "brein" }),
    # Same default docker-compose.yml uses; override with POSTGRES_PASSWORD.
    [string]$DbPassword = $(if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "password" }),  # pragma: allowlist secret
    [string]$DbName = "brein_test",
    [switch]$MountSource,
    # The tree to test; scripts/export-public.py points this at the exported copy.
    [string]$Repo = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
# The .env stays with this script's own repo: an exported tree has none.
$own = Split-Path -Parent $PSScriptRoot
$network = "${Project}_default"
$postgres = "${Project}-postgres-1"
$url = "postgresql+asyncpg://${DbUser}:${DbPassword}@postgres:5432/${DbName}"

# Idempotent: "already exists" is the normal case on every run after the first,
# and psql reports it on stderr, which PowerShell would otherwise treat as fatal.
$ErrorActionPreference = "Continue"
docker exec $postgres psql -U $DbUser -d postgres -c "CREATE DATABASE $DbName" 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

$args = @(
    "run", "--rm",
    "--network", $network,
    "--env-file", (Join-Path $own ".env"),
    "-e", "DATABASE_URL=$url",
    "-e", "BREIN_TEST_DATABASE_URL=$url",
    "-v", "${Repo}\tests:/app/tests"
)
if ($MountSource) {
    # Tests import the working tree instead of the image's copy — no rebuild per edit.
    $args += "-v", "${Repo}\brein:/app/brein:ro"
}
$args += @(
    "-v", "${Repo}\requirements-dev.txt:/app/requirements-dev.txt:ro",
    "-w", "/app",
    "${Project}-${Project}",
    # pytest is not in the runtime image: shipping test dependencies to
    # production was the point of splitting the requirements. uv is already
    # there, so installing them here costs a couple of seconds.
    "sh", "-c",
    "uv pip install -q -r /app/requirements-dev.txt && python -m pytest $Path -q $Extra"
)

# pytest writes warnings to stderr, which PowerShell would otherwise raise as a
# NativeCommandError regardless of whether the tests themselves passed. The
# exit code is the thing that says.
$ErrorActionPreference = "Continue"
& docker @args
exit $LASTEXITCODE
