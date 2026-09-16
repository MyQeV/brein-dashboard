"""Run the Brein web app."""

import os
import sys

import uvicorn

# Make the brein package importable for this process and the uvicorn reloader subprocess.
_repo_root = os.path.dirname(os.path.abspath(__file__))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [_repo_root]
    + (
        os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if os.environ.get("PYTHONPATH")
        else []
    )
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

if __name__ == "__main__":
    # init_db() is not called here: the app's lifespan runs it on startup.
    # Calling it twice ran the schema DDL twice, and with reload=True it built
    # an engine in a process that then forks.
    # First-time admin: create via browser at /setup when no users exist (no terminal prompt).

    dev_mode = os.environ.get("BREIN_DEV", "").strip().lower() in ("1", "true", "yes")
    uvicorn.run(
        "brein.web.app:app",
        host="0.0.0.0",
        port=8001,
        reload=dev_mode,
    )
