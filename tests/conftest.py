import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "third_party/webarena"

# browser_env.env_config asserts every site URL at import; tests never open a browser
for name in ("SHOPPING", "SHOPPING_ADMIN", "REDDIT", "GITLAB", "MAP", "WIKIPEDIA", "HOMEPAGE"):
    os.environ.setdefault(name, f"http://{name.lower()}.invalid")

sys.path.insert(0, str(HARNESS))


@pytest.fixture(scope="session")
def tasks() -> list[dict[str, Any]]:
    with open(HARNESS / "config_files/test.raw.json") as f:
        data: list[dict[str, Any]] = json.load(f)
    return data
