import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lk47.sites import SITE_VARS

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.live


def run_task(task_id: int, result_dir: Path) -> dict[str, object]:
    # conftest sets placeholder site URLs for unit tests; the runner must see its own defaults
    env = {k: v for k, v in os.environ.items() if k not in SITE_VARS}
    env["PATH"] = f"{ROOT / '.venv/bin'}:{env['PATH']}"
    subprocess.run(
        [sys.executable, "-m", "lk47.runner.live", "--tasks", str(task_id), "--result-dir", str(result_dir)],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    row: dict[str, object] = json.loads((result_dir / "ledger.jsonl").read_text().splitlines()[-1])
    return row


@pytest.mark.skipif(os.environ.get("LK47_LIVE") != "1", reason="needs running containers; set LK47_LIVE=1")
def test_two_live_runs_of_one_task_produce_the_same_action_hash(tmp_path: Path) -> None:
    first = run_task(0, tmp_path / "a")
    second = run_task(0, tmp_path / "b")
    assert first["score"] == 1.0
    assert first["action_hash"] == second["action_hash"]
    assert first["answer"] == second["answer"]
