from __future__ import annotations

from dataclasses import dataclass

from lk47.actions import NO_ANSWER


@dataclass(frozen=True)
class Unachievable:
    pass


# an exact "N/A" is matched before the harness consults its judge
UNACHIEVABLE_ANSWER = "N/A"


def stop_answer(value: str | Unachievable) -> str:
    if isinstance(value, Unachievable):
        return UNACHIEVABLE_ANSWER
    return value.strip() or NO_ANSWER
