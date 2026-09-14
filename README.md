# Brein-dashboard

Centralized dashboard and management hub for your media stack. 
FastAPI + PostgreSQL API on port **8001**, Next.js frontend on port **3100**.

This is part of my private brein repository that i wanted to set public.

## What Brein does

### Dashboard
Live overview of your Emby, Jellyfin or Plex server: total plays, watch time,
per-user breakdowns, and recent activity. Stats are cached and refreshed
periodically.
<img width="1690" height="836" alt="image" src="https://github.com/user-attachments/assets/4f75ea5d-b834-4244-8390-f13b15d516c6" />
<img width="1693" height="301" alt="image" src="https://github.com/user-attachments/assets/d8be9306-c0e2-4b3e-bcff-61726f24f8f4" />

### Now playing
Real-time playback state pushed to the UI via WebSocket. Updates every 10
seconds.
<img width="1901" height="331" alt="image" src="https://github.com/user-attachments/assets/045603c9-4018-4b92-9b18-602d7f7bcd77" />

### Release calendar (Sonarr/Radarr)
Unified calendar view of upcoming and recently released content pulled from
Sonarr and Radarr.
<img width="1693" height="869" alt="image" src="https://github.com/user-attachments/assets/52e19db9-8b6d-4cb7-b8c4-ae7e49163493" />

### Downloads (SABnzbd)
Queue and history views for SABnzbd, with per-item pause/resume/delete and
server stats.

### Instance management
Add and manage connections to any number of supported services. Each
instance is tested on save, and connection health can be re-checked at any
time from the settings panel. Instances are grouped by service type.

### User management
- Create and manage local Brein users with role-based access
- Import users directly from an Emby server — avoids manual re-entry
- Per-user preferences (timezone, display settings)
- Login history and last-seen tracking per user

### Authentication
JWT-based auth with short-lived access tokens and longer-lived refresh
tokens. "Remember me" controls the refresh token lifetime. Tokens are
blacklisted on logout. Rate limiting is applied to all auth endpoints.

### Log viewer
Admin-accessible log viewer built into the settings UI. Logs rotate daily
and are retained for 30 days by default. Log level, retention period, and
file path are all configurable via environment variables.

### Background sync
Each media server or downloader instance you add gets its own background
sync tasks, run by a DB-driven scheduler:

| Service | Task | Default interval |
|---|---|---|
| Emby | Users sync | 60s |
| Emby | Activity log sync | 60s |
| Emby | Items sync | 1h |
| Jellyfin | Users sync | 60s |
| Jellyfin | Activity log sync | 60s |
| Jellyfin | Items sync | 1h |
| Plex | Users sync | 10min |
| Plex | Items sync | 1h |
| SABnzbd | Server stats sync | 1h |

Plus three global tasks: now-playing broadcast (10s), dashboard cache
refresh (10min) and expired-token cleanup (1h). Intervals are editable per
instance from `/settings/tasks` once the app is running.

Activity log entries that reference users by numeric ID are resolved
automatically via the server's API and cached — after the first full
resolution pass, no extra API calls are made.

## Supported services

| Service | What Brein does with it |
|---|---|
| Emby | Dashboard, now playing, user/library/activity sync, user import |
| Jellyfin | Dashboard, now playing, user/library/activity sync |
| Plex | Dashboard, now playing, user/library sync via a live WebSocket listener |
| Sonarr | Release calendar, queue/history/blocklist, missing, cutoff, events, tasks, backups |
| Radarr | Release calendar, queue/history/blocklist, collections, missing, cutoff, events, tasks, backups |
| SABnzbd | Download queue and history, server stats |

---

## Table of contents

- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Running](#running-the-app)
- [Testing](#testing)
- [Licence](#licence)

## Prerequisites

- Docker and Docker Compose

## Quick start

```bash
git clone https://github.com/MyQeV/brein-dashboard.git
cd brein-dashboard
cp .env.example .env
# Edit .env — set BREIN_SECRET_KEY (e.g. openssl rand -hex 32)
docker compose up -d --build
```

Open [http://localhost:3100](http://localhost:3100). On first run you will be
redirected to setup to create the first admin account. The frontend proxies
`/api`, `/token`, `/refresh` and `/ws` to the API (port 8001) so cookies stay
first-party — you generally don't need to talk to port 8001 directly.

## Configuration

Copy [`.env.example`](.env.example) to `.env` and configure the variables below.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BREIN_SECRET_KEY` | Yes | — | Secret for signing JWTs. Generate with `openssl rand -hex 32`. |
| `DATABASE_URL` | Yes | — | PostgreSQL async connection string (e.g. `postgresql+asyncpg://user:pass@db:5432/brein`). | <!-- pragma: allowlist secret -->
| `BREIN_ACCESS_TOKEN_EXPIRE_MINUTES` | No | 30 | Access token lifetime in minutes. |
| `BREIN_REFRESH_TOKEN_EXPIRE_DAYS` | No | 30 | Refresh token lifetime when "Remember me" is checked. |
| `BREIN_REFRESH_TOKEN_EXPIRE_DAYS_SESSION` | No | 7 | Refresh token lifetime when "Remember me" is unchecked. |
| `TZ` | No | UTC | IANA timezone applied to the app (dashboard/activity timestamps), PostgreSQL, and container logs (e.g. `Europe/Amsterdam`). |
| `POSTGRES_DATA_DIR` | No | `./data/postgres` | Host path for the PostgreSQL data volume. |
| `BREIN_DATA_DIR` | No | `./data/brein` | Host path for the app data volume (logs, backups, etc.). |
| `BREIN_FRONTEND_PORT` | No | 3100 | Host port for the frontend container. |
| `BREIN_LOG_DIR` | No | `/app/data/logs` | Directory for rotating log files (inside the container). |
| `BREIN_LOG_RETENTION_DAYS` | No | 30 | Days to keep rotated log files. |
| `BREIN_LOG_LEVEL` | No | INFO | Log level: DEBUG, INFO, WARNING, ERROR. |
| `BREIN_EMBY_ACTIVITY_SYNC_INTERVAL_SECONDS` | No | 60 | Emby/Jellyfin activity log sync interval, in seconds. |

See [`.env.example`](.env.example) for the full list, including reverse-proxy
trust, cookie security, database pool sizing and per-task sync intervals.

## Running the app

```bash
# Build and start all services (PostgreSQL + API + frontend)
docker compose up -d --build

# Follow logs
docker compose logs -f brein

# Stop
docker compose down
```

The frontend is at [http://localhost:3100](http://localhost:3100), the JSON
API at [http://localhost:8001](http://localhost:8001). Database and log data
persist in the configured volumes.

## Testing

Tests run inside Docker using a separate `brein_test` database.

```powershell
# Windows (PowerShell)
./scripts/run-tests-docker.ps1
./scripts/run-tests-docker.ps1 -Path tests/test_security.py   # one file
./scripts/run-tests-docker.ps1 -MountSource                   # against the working tree
```

On Linux/macOS, run the equivalent `docker run` the script issues directly —
see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licence

AGPL-3.0, see [LICENSE](LICENSE).
