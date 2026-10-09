from __future__ import annotations

from collections.abc import Generator

from lk47.actions import Act, Click, Locator, Press, Type
from lk47.snapshot import PageSnapshot

Steps = Generator[Act, PageSnapshot, PageSnapshot]


def replace_text(locator: Locator, text: str) -> Steps:
    # the harness types at the caret and never clears, so a prefilled field is selected first
    yield Click(locator)
    yield Press("Control+a")
    return (yield Type(locator, text))


def choose_option(select: Locator, label: str) -> Steps:
    # typing the label into a focused select picks the first option that starts with it;
    # only the first type on a given select takes effect, so each select is set once
    return (yield Type(select, label))


def select_contiguous(select: Locator, first_label: str, count: int) -> Steps:
    snapshot = yield Click(select.inside("option").having_text(first_label))
    for _ in range(count - 1):
        snapshot = yield Press("Shift+ArrowDown")
    return snapshot
