from collections import Counter
from typing import Any

from lk47.intents import parse
from lk47.intents.slots import SLOT_KINDS
from lk47.intents.templates_data import TEMPLATES


def test_every_slot_has_a_kind() -> None:
    names = {s for _, _, slots in TEMPLATES for s in slots}
    assert names <= set(SLOT_KINDS), sorted(names - set(SLOT_KINDS))
    assert set(SLOT_KINDS) <= names, sorted(set(SLOT_KINDS) - names)


def test_templates_data_matches_config(tasks: list[dict[str, Any]]) -> None:
    expected = {(t["intent_template_id"], t["intent_template"]) for t in tasks}
    assert {(tid, text) for tid, text, _ in TEMPLATES} == expected
    assert len(expected) == 241
    assert len({tid for tid, _ in expected}) == 190


def test_all_812_intents_parse_to_ground_truth(tasks: list[dict[str, Any]]) -> None:
    failures: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for t in tasks:
        try:
            task = parse(t["intent"])
        except LookupError as e:
            failures[type(e).__name__] += 1
            examples.setdefault(type(e).__name__, f"task {t['task_id']}: {e}")
            continue
        if task.template_id != t["intent_template_id"]:
            failures["wrong_template"] += 1
            examples.setdefault("wrong_template", f"task {t['task_id']}: got {task.template_id}")
            continue
        got = {k: v.raw for k, v in task.slots.items()}
        # list and int slot values appear in the intent as their Python repr
        want = {k: str(v) for k, v in t["instantiation_dict"].items()}
        if got != want:
            failures["wrong_slots"] += 1
            examples.setdefault("wrong_slots", f"task {t['task_id']}: {got} != {want}")
    assert not failures, f"{dict(failures)} of {len(tasks)}; first of each: {examples}"
