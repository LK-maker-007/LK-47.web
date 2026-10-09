from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser

from lk47.plan import AnswerKind
from lk47.typed import values, verified_response

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "third_party/webarena-verified/webarena-verified.json"

_recording: dict[str, Path | None] = {"har": None}
NOT_STATIC = re.compile(
    r"^(?!.*\.(?:js|css|png|jpe?g|gif|svg|webp|woff2?|ttf|eot|ico|map)(?:\?|$)).*$"
)
_new_context = Browser.new_context


def intents() -> dict[int, str]:
    with open(DATASET) as f:
        return {t["task_id"]: t["intent"] for t in json.load(f)}


def write_config(task_id: int, intent: str, out_dir: Path) -> Path:
    # the harness runs an episode from a config file: this copy carries the Verified wording and no
    # grading block, because the original graders open pages that would land in the trace
    with open(f"config_files/{task_id}.json") as f:
        config = json.load(f)
    config["intent"] = intent
    config["eval"]["eval_types"] = []
    path = out_dir / f"{task_id}.json"
    path.write_text(json.dumps(config))
    return path


def _recording_context(self: Browser, **kwargs: Any) -> Any:
    har = _recording["har"]
    if har is not None:
        kwargs["record_har_path"] = str(har)
        kwargs["record_har_content"] = "embed"
        kwargs["record_har_url_filter"] = NOT_STATIC
    return _new_context(self, **kwargs)


def install() -> dict[int, str]:
    from browser_env.envs import ScriptBrowserEnv  # noqa: PLC0415

    Browser.new_context = _recording_context  # type: ignore[method-assign]
    close = ScriptBrowserEnv.close

    def close_context_first(self: ScriptBrowserEnv) -> None:
        # Playwright writes the HAR when its context closes; the harness only stops the driver
        if self.reset_finished:
            self.context.close()
        close(self)

    ScriptBrowserEnv.close = close_context_first
    return intents()


def prepare(task_id: int, intent: str, result_dir: Path) -> str:
    task_dir = result_dir / "verified" / str(task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    _recording["har"] = task_dir / "network.har"
    return str(write_config(task_id, intent, task_dir))


def respond(task_id: int, result_dir: Path, agent: Any) -> None:
    retrieves = agent.answer_kind not in (None, AnswerKind.NONE)
    task_type = "RETRIEVE" if retrieves else "MUTATE"
    data = None
    if retrieves and isinstance(agent.answer, str):
        data = values(agent.template_id, agent.answer, agent.intent)
    response = verified_response(task_type, agent.answer, agent.failure, data)
    path = result_dir / "verified" / str(task_id) / "agent_response.json"
    path.write_text(json.dumps(response, ensure_ascii=False))
