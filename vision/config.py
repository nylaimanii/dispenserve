"""Settings from the environment, with an optional gitignored .env at the repo root.

Every setting has a working default, so nothing here is required to run.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path=REPO_ROOT / ".env"):
    """Minimal KEY=VALUE loader. Real environment variables win over the file."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.split(" #", 1)[0].split("\t#", 1)[0]  # trailing comment
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env(key, default=None):
    value = os.environ.get(key, "").strip()
    return value if value else default


def env_int(key, default):
    try:
        return int(env(key, default))
    except (TypeError, ValueError):
        return default
