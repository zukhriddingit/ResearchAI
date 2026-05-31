from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "demo" / "lora_fixture.json"


@lru_cache(maxsize=1)
def load_lora_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

