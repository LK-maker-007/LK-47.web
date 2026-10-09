from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from lk47.intents.slots import (
    NAME_KINDS,
    SHAPES,
    SLOT_KINDS,
    SPECIFICITY,
    VERIFIED_SLOT_KINDS,
    WORDING_SLOT_KINDS,
    SlotKind,
    SlotValue,
)
from lk47.intents.templates_data import TEMPLATES
from lk47.intents.templates_verified import VERIFIED_TEMPLATES

SLOT = re.compile(r"\{\{(.+?)\}\}")

ALTERNATE_TEXTS: dict[int, tuple[str, ...]] = {
    1355: ("What is the rating of {{product}}. Please round to the nearest whole number",),
    352: ("Fork {{repo}}",),
}


class NoMatch(LookupError):
    pass


class Ambiguous(LookupError):
    pass


@dataclass(frozen=True)
class Task:
    template_id: int
    text: str
    slots: Mapping[str, SlotValue]


@dataclass(frozen=True)
class Compiled:
    template_id: int
    text: str
    pattern: re.Pattern[str]
    slot_names: tuple[str, ...]
    slot_kinds: tuple[SlotKind, ...]
    score: tuple[int, int]
    verified: bool = False


def _slot_body(kind: SlotKind, position: int, count: int, final_kind: SlotKind) -> str:
    if kind in SHAPES:
        return SHAPES[kind]
    if position == count - 1:
        return r".*?"
    # a name does not contain the separator written just before it, so the slot ahead of a
    # final name keeps the last occurrence of that separator; every other slot stops early
    if position == count - 2 and final_kind in NAME_KINDS:
        return r".+"
    return r".+?"


def _compile(
    template_id: int, text: str, renames: Mapping[str, str | None] | None = None
) -> Compiled:
    overrides = WORDING_SLOT_KINDS.get((template_id, text), {})
    matches = list(SLOT.finditer(text))
    if renames is None:
        names = tuple(m.group(1) for m in matches)
        kinds = tuple(overrides.get(n, SLOT_KINDS[n]) for n in names)
    else:
        names = tuple(renames[m.group(1)] or m.group(1) for m in matches)
        kinds = tuple(
            overrides.get(n) or SLOT_KINDS.get(n) or VERIFIED_SLOT_KINDS.get(n, SlotKind.FREE_TEXT)
            for n in names
        )
    final_kind = kinds[-1] if kinds else SlotKind.FREE_TEXT
    parts: list[str] = []
    cursor = 0
    literal_len = 0
    for i, m in enumerate(matches):
        literal_len += m.start() - cursor
        parts.append(re.escape(text[cursor : m.start()]))
        body = _slot_body(kinds[i], i, len(matches), final_kind)
        parts.append(f"(?P<s{i}>{body})")
        cursor = m.end()
    literal_len += len(text) - cursor
    parts.append(re.escape(text[cursor:]))
    specificity = sum(SPECIFICITY.get(k, 0) for k in kinds)
    return Compiled(
        template_id,
        text,
        re.compile("".join(parts)),
        names,
        kinds,
        (literal_len, specificity),
        renames is not None,
    )


@lru_cache(maxsize=1)
def grammar() -> tuple[Compiled, ...]:
    original = tuple(
        _compile(template_id, variant)
        for template_id, text, _ in TEMPLATES
        for variant in (text, *ALTERNATE_TEXTS.get(template_id, ()))
    )
    known = {(c.template_id, c.text) for c in original}
    verified = tuple(
        _compile(template_id, text, dict(slots))
        for template_id, text, slots in VERIFIED_TEMPLATES
        if (template_id, text) not in known
    )
    return original + verified


def parse(intent: str) -> Task:
    hits: list[tuple[tuple[int, int, bool], Task]] = []
    for c in grammar():
        m = c.pattern.fullmatch(intent)
        if m is None:
            continue
        slots = {
            name: SlotValue(kind, m.group(f"s{i}"))
            for i, (name, kind) in enumerate(zip(c.slot_names, c.slot_kinds, strict=True))
        }
        task = Task(c.template_id, intent if c.verified else c.text, slots)
        hits.append(((*c.score, not c.verified), task))
    if not hits:
        raise NoMatch(intent)
    # most literal text first, then the more specific slot shapes
    best = max(score for score, _ in hits)
    top = [task for score, task in hits if score == best]
    if any(t != top[0] for t in top):
        raise Ambiguous(f"{intent!r} matches templates {sorted(t.template_id for t in top)}")
    return top[0]
