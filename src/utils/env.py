import os
from pathlib import Path

from dotenv import dotenv_values

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

ENV: dict[str, str] = {**dotenv_values(_ENV_FILE), **os.environ}
