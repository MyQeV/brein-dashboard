import logging
import logging.config
import logging.handlers
import os
import pathlib


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def setup_logging() -> None:
    log_level = os.environ.get("BREIN_LOG_LEVEL", "INFO").upper()
    log_dir = os.environ.get("BREIN_LOG_DIR", "/app/data/logs")
    log_file = os.environ.get("BREIN_LOG_FILE", "brein.log")
    # Parsed defensively, like every setting in config.py. These ran bare
    # int() at import time, so `BREIN_LOG_ROTATE_UTC=true` — the form every
    # other boolean in .env.example takes — raised before the log handlers
    # existed: uvicorn could not load the app and `restart: unless-stopped`
    # looped it with a traceback nobody could read.
    retention_days = _int_env("BREIN_LOG_RETENTION_DAYS", 30)
    rotate_utc = _bool_env("BREIN_LOG_ROTATE_UTC", False)

    pathlib.Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s"
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "standard",
                },
                "file": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "filename": log_path,
                    "when": "midnight",
                    "interval": 1,
                    "backupCount": retention_days,
                    "utc": rotate_utc,
                    "formatter": "standard",
                },
            },
            "loggers": {
                # httpx logs the full request URL at INFO, and SABnzbd (like
                # several *arr endpoints) carries its API key in the query
                # string — so every poll wrote a live credential to brein.log.
                "httpx": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
                # websockets logs the upgrade request at DEBUG, and the Emby
                # and Plex listeners carry their token in that URL.
                "websockets": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
            "root": {"handlers": ["console", "file"], "level": log_level},
        }
    )


def get_log_dir() -> str:
    return os.environ.get("BREIN_LOG_DIR", "/app/data/logs")


def get_log_file() -> str:
    return os.environ.get("BREIN_LOG_FILE", "brein.log")
