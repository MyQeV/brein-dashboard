# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**Brein** is a centralized dashboard and management hub for media servers (Emby, Jellyfin,
Plex) with integrations for content management (Sonarr, Radarr) and downloads (SABnzbd).

Two services, both run by `docker-compose.yml`:

- **API** — FastAPI + PostgreSQL + SQLModel on port **8001**. JSON only; it serves no HTML.
- **Frontend** — a Next.js app in `frontend/`, on port **3100**, which proxies `/api`, `/token`, `/refresh` and `/ws` to the API so cookies stay first-party.

There are no templates, no vendored HTMX, and no `HX-Request` handling anywhere in the tree.

## Tech Stack

- **FastAPI** 0.134+ — async web framework, Uvicorn ASGI server
- **SQLModel** 0.0.22 — ORM combining SQLAlchemy + Pydantic (async, asyncpg driver)
- **PostgreSQL** 16 — primary database (Docker)
- **Next.js 16** (React 19, Tailwind v4, Biome) — the frontend, in `frontend/`
- **WebSockets** — real-time now-playing broadcasts
- **slowapi** — rate limiting middleware
- **PyJWT** + **pwdlib** (argon2) — authentication
- **httpx** — async HTTP client for integrations
- **Ruff** — linter/formatter (replaces black/flake8/isort)
- **MyPy** — static type checking
- **uv** — fast package installer (used in Docker)
- **pytest** — test framework (`scripts/run-tests-docker.ps1`)

## Extension seam

Brein ships with Emby, Jellyfin, Plex, Sonarr, Radarr and SABnzbd built in. Anything
else plugs in through an extension seam rather than being wired into core files by name:

- `brein/extensions.py` — the registry (`ServiceType`, `Tab`, `Downloader`,
  `Extension`, `load_extensions()`). Core registers its own service types and the
  SABnzbd downloader from `brein/core_services.py` through the same object.
- `brein/extras/` — one subpackage per optional integration, each exposing a
  `register(ext)` function; `brein/extras/__init__.py` lists them by name in
  `EXTRAS`. **In this tree `EXTRAS` is empty** — there are no optional integrations
  here, so `import brein.web.app` succeeds with nothing beyond core.
- `frontend/src/extras/index.ts` — the matching frontend seam (extra arr-table
  configs, restartable/pingable service ids). Empty in this tree.
- Consumers read the registry instead of naming services: `web/app.py` includes
  `load_extensions().routers` after its own; `jobs/scheduled_task_registry.py`
  merges `load_extensions().task_types`; `web/routers/services.py` exposes
  `icon`/`tabs`/`arr_tables` per service through `GET /api/service-types`, which the
  frontend loads once and reads from a context instead of hardcoding service metadata.

If you want to add your own integration, add a subpackage under `brein/extras/`
with a `register(ext)` function and list it in `EXTRAS`; nothing in core needs
to change.

## Project Structure

```
brein/                         # the Python package — everything below lives here
├── main.py                    # Dev entry point (reloads only with BREIN_DEV=1)
├── config.py                  # Environment-based configuration
├── cache.py                   # In-process TTL cache (no Redis)
├── db.py                      # Async engine, session factory, schema init & repairs
├── background.py              # spawn() for fire-and-forget tasks, with strong refs
├── backups.py                 # Database export/import
├── logging_setup.py           # Rotating file + console handlers
├── extensions.py              # The core/extras registry (see Extension seam above)
├── core_services.py           # Registers Brein's own service types + downloader
│
├── web/                       # FastAPI app
│   ├── app.py                 # Routers, middleware, lifespan
│   ├── auth.py                # JWT, password hashing, the auth dependencies
│   ├── csrf.py                # Double-submit token for cookie-authenticated writes
│   ├── rate_limit.py          # slowapi config, trusted-proxy handling
│   ├── routers/               # 18 routers, registered in app.py, plus whatever
│   │   │                      # load_extensions() adds (nothing in this tree)
│   │   ├── auth.py            # Login, logout, refresh, user CRUD
│   │   ├── dashboard.py       # Metrics, drill-downs, concurrency, idle users, library
│   │   ├── calendar.py, now_playing.py, instances.py, services.py
│   │   ├── settings.py, tasks.py, database.py, user_preferences.py
│   │   ├── emby.py, plex.py, radarr.py, sonarr.py, sabnzbd.py
│   │   ├── downloads.py, image.py, users_import.py
│   └── static/icons/          # Service logos, served to the frontend
│
├── models/tables.py           # 38 SQLModel table definitions
│
├── store/                     # Data access layer (29 modules)
│   ├── metrics_activity.py, metrics_library.py, metrics_playback.py,
│   │   metrics_users.py, metrics_helpers.py      # Emby metrics, split by subject
│   ├── jellyfin_dashboard_metrics.py, plex_dashboard_metrics.py
│   │                                            # near-copies of the four above
│   ├── dashboard_insights.py  # Cross-backend: concurrency, idle users, unwatched
│   ├── emby_*/jellyfin_*/plex_*                 # users, items, sessions, activity log
│   └── users.py, system_settings.py, scheduled_tasks.py, user_preferences.py, …
│
├── integrations/
│   ├── api/                   # 6 clients (emby, jellyfin, plex, radarr, sonarr,
│   │                          # sabnzbd); base.py carries the SSRF guard & shared HTTP
│   ├── websockets/            # Emby and Plex live listeners
│   └── registry.py            # test_connection registry
│
├── extras/                    # Empty in this tree: __init__.py with EXTRAS = []
│
└── jobs/                      # Background workers (see Background Jobs below)

frontend/                      # Next.js app (port 3100)
└── src/
    ├── app/(app)/             # dashboard/, calendar/, now-playing/, instance/, settings/
    ├── components/            # ui/, charts/, drill-modal, sessions-by-day, layout/
    ├── extras/                # Empty in this tree — see Extension seam above
    └── lib/                   # api + client-fetch, format, types, params

tests/                         # pytest; see Testing
scripts/                       # run-tests-docker.ps1, run-tests.ps1, run_first_time_setup.py
```

## Database

- **Schema**: Created via `SQLModel.metadata.create_all()` on startup — no Alembic migrations
- **Runtime upgrades**: `db.py` reconciles an older database at startup — it adds columns the models declare and the database lacks (taking NOT NULL values from the model's own default), upgrades `users.username` to CITEXT, ensures the instance-scoped foreign keys cascade, and creates the indexes the dashboard relies on. `create_all` never alters an existing table, so this is what stands in for migrations.
- **Async sessions**: Use `AsyncSession` via `get_session` dependency
- Notable tables: `users`, `app_instances`, `emby_users`, `emby_items`, `emby_activity_log_entries`, `emby_playback_sessions`, the Jellyfin and Plex equivalents, the `*_metrics_snapshot*` tables the dashboard reads, `refresh_tokens`, `token_blacklist`, `system_settings`, `user_preferences`, `sabnzbd_server_stats_snapshots`, `plex_ws_events`, `scheduled_tasks`, `scheduled_task_runs`.
- **Ids are per-server.** Item, series and user ids repeat across instances, so anything counting or joining them must be scoped by `(instance_id, id)` — a bare `COUNT(DISTINCT item_id)` silently merges two servers' libraries.

## Background Jobs (DB-driven scheduler)

Brein runs **one** scheduler coroutine (`brein/jobs/scheduled_task_runner.py`) that polls the `scheduled_tasks` table every 5 seconds and spawns due tasks. State (last_run_at, last_status, last_duration_ms) and run history (`scheduled_task_runs`) are persisted in PostgreSQL — survives restarts.

- **TaskTypes** are registered in `brein/jobs/scheduled_task_registry.py`. Adding a new background job = add a `TaskType` entry there + a `run_once`/`*_sync_once(instance, session)` function in `brein/jobs/` (or register one from `brein/extras/` through the extension seam).
- **Reconciler** (`brein/jobs/scheduled_task_reconciler.py`) seeds one row per (TaskType × matching `AppInstance`) plus one row per global TaskType. Called on startup and after `POST /api/instances`. Existing user-edited `interval_seconds`/`enabled` are preserved on subsequent reconcile passes.
- **Per-instance** task rows are cascade-deleted with their `AppInstance` (FK ON DELETE CASCADE).
- **Pause logic**: runner skips a task when `task.enabled = false` OR (instance-bound AND `app_instances.active = false`). No separate `paused` column.
- **Run history pruning**: hourly inline pass deletes `scheduled_task_runs` older than 14 days.
- **UI**: `/settings/tasks` lists tasks grouped by instance (Global card + per-instance cards); each row supports run-now, enable/disable, and inline interval edit. Detail page at `/settings/tasks/{id}` shows last 50 runs with status, duration, and truncated traceback (max 4000 chars).

| Default TaskType key | Category | Service | Default interval |
|---|---|---|---|
| `dashboard_cache_refresh` | cache | (global) | 600s |
| `token_cleanup` | cleanup | (global) | 3600s |
| `now_playing_broadcast` | broadcast | (global) | 10s |
| `emby_activity_log_sync` | sync | emby | 60s |
| `emby_users_sync` | sync | emby | 60s |
| `emby_items_sync` | sync | emby | 3600s |
| `jellyfin_activity_log_sync` | sync | jellyfin | 60s |
| `jellyfin_users_sync` | sync | jellyfin | 60s |
| `jellyfin_items_sync` | sync | jellyfin | 3600s |
| `plex_users_sync` | sync | plex | 600s |
| `plex_items_sync` | sync | plex | 3600s |
| `sabnzbd_server_stats_sync` | sync | sabnzbd | 3600s |

## Development Commands

### Run locally (dev)
```bash
python main.py          # Starts uvicorn --reload on port 8001
```

### Docker (production-style)
```bash
docker compose up -d --build    # Build and start all services
docker compose down             # Stop services
docker compose logs -f brein    # Follow logs
```

### Testing
```powershell
./scripts/run-tests-docker.ps1                              # whole suite
./scripts/run-tests-docker.ps1 -Path tests/test_security.py # one file
./scripts/run-tests-docker.ps1 -Extra "-x"                  # stop on first failure
./scripts/run-tests-docker.ps1 -MountSource                 # against the working tree, no rebuild
```

Tests run inside the app image against the compose Postgres, in a
`brein_test` database the script creates. Run them that way rather than
with a bare `pytest`: `conftest.py` only *defaults* `DATABASE_URL`, so a
developer `.env` pointing at localhost wins and every database-backed
test fails with a connection error instead of skipping.

### Code Quality
```bash
ruff check .                    # Lint (replaces flake8)
ruff format .                   # Format (replaces black)
ruff check --fix .              # Auto-fix lint issues
mypy .                          # Type checking
```

### Pre-commit hooks
```bash
pre-commit run --all-files      # Run all hooks manually
pre-commit install              # Install hooks into git
```

## Environment Variables

Key variables (see `.env.example`):
- `BREIN_SECRET_KEY` — JWT signing key (required)
- `DATABASE_URL` — PostgreSQL connection string (required)
- `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS`
- `EMBY_ACTIVITY_SYNC_INTERVAL` (default 60s)
- `POSTGRES_DATA_DIR` / `BREIN_DATA_DIR` — volume mount paths

## Naming Conventions

- **Files/Modules**: `snake_case`
- **Classes**: `PascalCase`
- **Functions/Variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private methods**: `_prefixed_with_underscore`
- **API routes**: kebab-case URLs, snake_case Python handlers

## Key Patterns

- Routers use FastAPI `Depends(get_session)` for DB sessions
- Auth uses `Depends(get_current_user)` for protected routes; state-changing routes take `AdminUser`
- Every endpoint returns JSON — the API serves no HTML
- WebSocket connections managed in `now_playing.py`
- Integration clients inherit from `integrations/api/base.py:BaseAPI`
- Store layer is async; always `await` store function calls
- `cache.py` provides in-process TTL caching (no Redis dependency)

## Rules

- **Never run linters, type checkers, or pre-commit hooks unless explicitly asked.** Do not run `ruff`, `mypy`, or `pyright` unprompted.
- **When asked to remove or edit something, do it immediately.** Do not repeatedly read the file without acting.
- **Prefer editing existing files** over creating new ones.
- **Do not add unrequested features, refactors, comments, or docstrings.**
- **Never run or test the app locally.** Do not use `python main.py`, `uvicorn`, `pytest`, or any local execution. All runtime testing goes through Docker only.
- **When adding a new route or router, verify it is registered** in `web/app.py` (or the relevant `include_router` call) before finishing.
- **Always add an import and the code that uses it in the same edit.** Ruff runs as a pre-commit hook and automatically removes unused imports. If you add an import in one edit and the consuming code in a separate edit, ruff will strip the import before the second edit lands, causing a `NameError`. Add both in a single atomic edit.

## Environment

- **Docker is the deployment target.** All execution, testing, and validation happens inside Docker containers.
- All production-style testing goes through Docker (`docker compose up -d --build`).

## Architecture Constraints

- **The API is JSON.** No template rendering, no HTML responses.
- **Tailwind only** in the frontend — no Bootstrap, no CSS-in-JS, no new styling system. Reuse the tokens in `frontend/src/app/globals.css`, which bridge the app's five themes.
- **Charts are hand-built** (`frontend/src/components/charts/`): every chart — doughnuts included — is drawn from divs/SVG, not a charting library, sized in pixels because a percentage height has nothing to resolve against inside a flex column. Categorical colours come from `chart-theme.ts` — the first eight hues are validated for colour-vision deficiency and contrast against both themes, the eight after that extend the set for stacked charts only.
- **Theme-aware**: every colour goes through a token, so both light and dark work. The theme is an explicit `data-theme` attribute, set pre-paint.

## Bug Fixes

- When fixing a bug, **grep the entire codebase for all similar occurrences** before fixing any single one. Fix all instances at once.
- After making changes to routes, imports, or config, verify no other file depends on the old name/path.

## Frontend Changes

- The app lives in `frontend/src/app/`, App Router, mostly server components that `apiFetch` and hand data to a small `"use client"` view.
- **Verify the field names against the API before reading them.** The stores emit different keys for the same idea (`label` vs `display_label` vs `display_name`; `total_seconds` vs `watch_time_seconds`), and the readers return a dash or zero on a miss — so a wrong name renders a chart of zeros with no error anywhere.
- Reuse `components/ui/*`, `components/charts/*` and `components/sessions-by-day.tsx` rather than re-implementing a table, a modal or a session list.
- `docker compose build frontend` **exits 0 even when the build fails** — read the output for "Build error occurred" / "failed to solve" rather than trusting the exit code.

## Security Notes

- Do not commit `.env` files (detect-secrets pre-commit hook active)
- JWT tokens use `BREIN_SECRET_KEY` — keep this secret
- Passwords hashed with Argon2 via pwdlib
- Rate limiting enforced on auth endpoints via slowapi
