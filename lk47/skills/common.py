from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, TypeVar

from lk47.actions import Act, Hover, Locator
from lk47.snapshot import PageSnapshot

T = TypeVar("T")

Skill = Generator[Act, PageSnapshot, T]
SkillFactory = Callable[..., Skill[Any]]


class Precondition(RuntimeError):
    pass


class Postcondition(RuntimeError):
    pass


class Budget(RuntimeError):
    pass


REGISTRY: dict[str, SkillFactory] = {}


def settle(n: int) -> Hover:
    # an observation that only waits for the page; consecutive waits alternate their target, as
    # three identical actions in a row end the episode
    return Hover(Locator.css(("body", "html")[n % 2]))
