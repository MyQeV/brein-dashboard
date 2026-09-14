# Contributing to Brein

Thanks for considering a contribution. This project is AGPL-3.0; by
submitting a change you agree it is contributed under that licence. No
sign-off / DCO is required.

## Running the app

Docker is the only supported way to run and test Brein — there is no
"run it locally with a venv" path.

```bash
git clone https://github.com/MyQeV/brein-dashboard.git
cd brein-dashboard
cp .env.example .env
# set BREIN_SECRET_KEY, e.g. openssl rand -hex 32
docker compose up -d --build
```

The frontend is on `http://localhost:3100`, the API on `http://localhost:8001`.

## Tests

The suite needs a database it may create tables in and a `DATABASE_URL`
pointing at the compose network rather than whatever your `.env` holds.
`tests/conftest.py` only *defaults* `DATABASE_URL`, so a bare `pytest`
against a host `.env` fails every database-backed test with a connection
error instead of skipping it.

On Windows, use the provided script:

```powershell
./scripts/run-tests-docker.ps1                              # whole suite
./scripts/run-tests-docker.ps1 -Path tests/test_security.py # one file
./scripts/run-tests-docker.ps1 -Extra "-x"                  # stop on first failure
./scripts/run-tests-docker.ps1 -MountSource                 # against the working tree, no rebuild
```

There is no separate Linux script; run the same `docker run` the
PowerShell script issues, against the compose Postgres. `docker-compose.yml`
pins the compose project name to `brein` (the `name:` key), so the
container/network/image names below are stable regardless of what directory
you cloned into:

```bash
DB_USER=${POSTGRES_USER:-brein}
DB_PASSWORD=${POSTGRES_PASSWORD:-password}  # pragma: allowlist secret
DB_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@postgres:5432/brein_test"

docker exec brein-postgres-1 psql -U "$DB_USER" -d postgres -c "CREATE DATABASE brein_test" || true

docker run --rm \
  --network brein_default \
  --env-file .env \
  -e DATABASE_URL="$DB_URL" \
  -e BREIN_TEST_DATABASE_URL="$DB_URL" \
  -v "$(pwd)/tests:/app/tests" \
  -v "$(pwd)/requirements-dev.txt:/app/requirements-dev.txt:ro" \
  -w /app \
  brein-brein \
  sh -c "uv pip install -q -r /app/requirements-dev.txt && python -m pytest tests/ -q"
```

Add `-v "$(pwd)/brein:/app/brein:ro"` to run against the working tree
instead of the image's copy, matching `-MountSource`.

Frontend checks run from `frontend/`:

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm exec biome check src
```

## Pre-commit

```bash
pre-commit install
pre-commit run --all-files
```

This runs `ruff` (lint, `--fix`), `ruff-format`, `mypy`, and `detect-secrets`,
plus the usual whitespace/YAML/JSON/merge-conflict/large-file hooks — see
[`.pre-commit-config.yaml`](.pre-commit-config.yaml) for the exact list.

## Pull requests

- Keep a PR small and focused on one topic — separate refactors from
  behaviour changes.
- Add or update tests for any behaviour change.
- CI (backend tests, frontend typecheck + Biome, Docker build) must be
  green before merge.
- Describe *why* the change is needed, not just what it does.
