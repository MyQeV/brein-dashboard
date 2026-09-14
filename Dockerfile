FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app
ENV UV_SYSTEM_PYTHON=1
ENV UV_NO_CACHE=1

# Pinned: :latest would change the installer under a rebuild of an old commit.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Copy the repo root into /app so "brein.web.app" resolves via PYTHONPATH=/app.
# The Next frontend has its own image and is excluded in .dockerignore.
COPY . /app/

# NOTE: this image runs as root, which is not ideal. Dropping to a non-root
# user needs the bind-mounted /app/data to be writable by that uid, and on an
# existing install it is owned by the host user — the container then cannot
# open its own log file. Changing this means picking a uid and telling
# operators to chown their data directory, so it is left as a deliberate
# decision rather than a silent break on upgrade.

EXPOSE 8001

CMD ["uvicorn", "brein.web.app:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
