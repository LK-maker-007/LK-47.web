from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path

from lk47.runner import ledger, reset, verified
from lk47.runner.args import harness_namespace
from lk47.sites import SITE_VARS

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "third_party/webarena"

DEFAULT_SITES = {
    "SHOPPING_ADMIN": "http://localhost:7780/admin",
    "SHOPPING": "http://localhost:7770",
    "REDDIT": "http://localhost:9999",
    "GITLAB": "http://localhost:8023",
    "MAP": "http://localhost:3000",
    "WIKIPEDIA": "http://localhost:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing",
    "HOMEPAGE": "http://localhost:4399",
}


class ResultCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.score: float | None = None
        self.error: str | None = None

    def reset(self) -> None:
        self.score = None
        self.error = None

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith("[Result] (PASS)"):
            self.score = 1.0
        elif message.startswith("[Result] (FAIL)"):
            self.score = 0.0
        elif message.startswith(("[Unhandled Error]", "[OpenAI Error]")):
            self.error = message


def reference_answers(task_id: int) -> str:
    # shown only for tasks the judge could not grade here; the agent never reads this file
    with open(f"config_files/{task_id}.json") as f:
        answers = json.load(f)["eval"].get("reference_answers")
    return json.dumps(answers, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, nargs="+", required=True)
    ap.add_argument("--result-dir", type=Path, required=True)
    ap.add_argument(
        "--reset-before",
        type=int,
        nargs="*",
        default=[],
        help="task ids before which the site container is recreated (docs/specs, reset points)",
    )
    ap.add_argument("--reset-site", default="shopping_admin")
    ap.add_argument(
        "--verified",
        action="store_true",
        help="give the WebArena-Verified wording, record network.har, write agent_response.json",
    )
    options = ap.parse_args(argv)

    for name in SITE_VARS:
        os.environ.setdefault(name, DEFAULT_SITES[name])
    result_dir = options.result_dir.resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "traces").mkdir(exist_ok=True)

    # run.py resolves config files, cookies and the auto-login script relative to the harness root
    os.chdir(HARNESS)
    sys.path.insert(0, str(HARNESS))
    import run  # noqa: PLC0415

    import lk47.skills.cross  # noqa: F401, PLC0415  registers its skills
    import lk47.skills.gitlab  # noqa: F401, PLC0415
    import lk47.skills.map  # noqa: F401, PLC0415
    import lk47.skills.reddit  # noqa: F401, PLC0415
    import lk47.skills.shopping  # noqa: F401, PLC0415
    import lk47.skills.shopping_admin  # noqa: F401, PLC0415
    from lk47.agent import LK47Agent  # noqa: PLC0415

    wordings = verified.install() if options.verified else {}

    capture = ResultCapture()
    logging.getLogger("logger").addHandler(capture)
    agent = LK47Agent()
    args = harness_namespace(str(result_dir))
    passed = 0
    ungraded = 0
    for task_id in options.tasks:
        if task_id in options.reset_before:
            waited = reset.recreate(options.reset_site)
            print(
                f"reset {options.reset_site} before task {task_id}: ready after {waited:.0f} s",
                flush=True,
            )
        capture.reset()
        started = time.monotonic()
        config = f"config_files/{task_id}.json"
        if options.verified:
            config = verified.prepare(task_id, wordings[task_id], result_dir)
        # run.py averages its scores after an evaluator error; the error itself is in the log
        with contextlib.suppress(ZeroDivisionError):
            run.test(args, agent, [config])
        if options.verified:
            verified.respond(task_id, result_dir, agent)
        answer = agent.codes[-1] if agent.codes and agent.codes[-1].startswith("page.stop") else ""
        row = ledger.Row(
            task_id=task_id,
            template_id=agent.template_id,
            score=None if options.verified else capture.score,
            steps=len(agent.codes),
            url_before_stop=agent.last_url,
            answer=answer,
            failure="; ".join(f for f in (agent.failure, capture.error) if f) or None,
            seconds=round(time.monotonic() - started, 1),
            action_hash=ledger.action_hash(agent.codes),
        )
        ledger.append(result_dir / "ledger.jsonl", row)
        passed += row.score == 1.0
        ungraded += row.score is None
        print(
            f"task {task_id}: score={row.score} steps={row.steps} failure={row.failure} "
            f"hash={row.action_hash}",
            flush=True,
        )
        if row.score is None:
            print(f"    answer={answer} reference={reference_answers(task_id)}", flush=True)
    print(f"passed {passed} of {len(options.tasks)}, ungraded {ungraded}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
