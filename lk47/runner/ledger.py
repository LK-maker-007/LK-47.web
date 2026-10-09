from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Row:
    task_id: int
    template_id: int | None
    score: float | None
    steps: int
    url_before_stop: str
    answer: str
    failure: str | None
    seconds: float
    action_hash: str


def action_hash(codes: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(codes).encode()).hexdigest()[:16]


def append(path: Path, row: Row) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
