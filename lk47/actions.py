from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from browser_env.actions import (
    create_playwright_action,
    create_stop_action,
    parse_playwright_code,
)
from browser_env.constants import PLAYWRIGHT_LOCATORS

Scalar = str | bool | int


# the harness regex for stop yields None on an empty answer and its constructor rejects None;
# a single space survives the round trip and cleans to the empty string in the grader
NO_ANSWER = " "


class InvalidAction(ValueError):
    pass


def _literal(value: Scalar) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _check_text(text: str, what: str) -> None:
    if '")' in text or "')" in text or "\n" in text or "\r" in text:
        raise InvalidAction(f"{what} cannot contain a quote-paren or a line break: {text!r}")


@dataclass(frozen=True)
class LocatorCall:
    method: str
    args: tuple[str, ...] = ()
    kwargs: tuple[tuple[str, Scalar], ...] = ()

    def __post_init__(self) -> None:
        if self.method not in PLAYWRIGHT_LOCATORS:
            raise InvalidAction(f"locator method {self.method!r} is not whitelisted")

    def render(self) -> str:
        parts = [_literal(a) for a in self.args] + [f"{k}={_literal(v)}" for k, v in self.kwargs]
        return f"{self.method}({', '.join(parts)})"


@dataclass(frozen=True)
class Locator:
    calls: tuple[LocatorCall, ...]

    @staticmethod
    def css(selector: str) -> Locator:
        # the harness splits the chain on dots outside parentheses; a selector that contains
        # parentheses breaks that split, so text matching goes through filter(has_text=...)
        if "(" in selector or ")" in selector:
            raise InvalidAction(f"parentheses are not allowed in a selector: {selector!r}")
        return Locator((LocatorCall("locator", (selector,)),))

    @staticmethod
    def role(role: str, name: str | None = None, exact: bool | None = None) -> Locator:
        kwargs: list[tuple[str, Scalar]] = []
        if name is not None:
            kwargs.append(("name", name))
        if exact is not None:
            kwargs.append(("exact", exact))
        return Locator((LocatorCall("get_by_role", (role,), tuple(kwargs)),))

    @staticmethod
    def label(text: str, exact: bool | None = None) -> Locator:
        kwargs = (("exact", exact),) if exact is not None else ()
        return Locator((LocatorCall("get_by_label", (text,), kwargs),))

    @staticmethod
    def placeholder(text: str) -> Locator:
        return Locator((LocatorCall("get_by_placeholder", (text,)),))

    @staticmethod
    def text(text: str, exact: bool | None = None) -> Locator:
        kwargs = (("exact", exact),) if exact is not None else ()
        return Locator((LocatorCall("get_by_text", (text,), kwargs),))

    def inside(self, selector: str) -> Locator:
        return Locator((*self.calls, LocatorCall("locator", (selector,))))

    def having_text(self, text: str) -> Locator:
        return Locator((*self.calls, LocatorCall("filter", (), (("has_text", text),))))

    def rooted(self, root: str) -> Locator:
        return Locator((LocatorCall("locator", (root,)), *self.calls))

    def nth(self, index: int) -> Locator:
        last = self.calls[-1]
        if last.method == "filter":
            return Locator((*self.calls, LocatorCall("locator", (f"nth={index}",))))
        if last.method != "locator" or len(last.args) != 1:
            raise InvalidAction("nth() applies only to a css locator or a filter")
        rewritten = LocatorCall("locator", (f"{last.args[0]} >> nth={index}",))
        return Locator((*self.calls[:-1], rewritten))

    def render(self) -> str:
        return "page." + ".".join(c.render() for c in self.calls)


@dataclass(frozen=True)
class Goto:
    url: str


@dataclass(frozen=True)
class Click:
    locator: Locator


@dataclass(frozen=True)
class Type:
    locator: Locator
    text: str


@dataclass(frozen=True)
class Select:
    locator: Locator
    option: str


@dataclass(frozen=True)
class Check:
    locator: Locator


@dataclass(frozen=True)
class Hover:
    locator: Locator


@dataclass(frozen=True)
class Press:
    key: str


@dataclass(frozen=True)
class Scroll:
    direction: Literal["up", "down"]


@dataclass(frozen=True)
class Stop:
    answer: str


@dataclass(frozen=True)
class Focus:
    tab: int


Act = Goto | Click | Type | Select | Check | Hover | Press | Scroll | Stop | Focus

_LOCATOR_ACTS = (Click, Type, Select, Check, Hover)


def _render_type(act: Type) -> str:
    if "\n" in act.text or "\r" in act.text:
        raise InvalidAction(f"typed text cannot contain a line break: {act.text!r}")
    target = act.locator.render()
    # the harness regex for fill is 'type|fill(...)': the word "type" anywhere in the code
    # matches first, with no text group, and the harness crashes on the None
    if "type" in target:
        raise InvalidAction(f"a fill target cannot contain the word 'type': {target}")
    # the harness maps the text it reads off the code through a key table that has no curly
    # quote or dash; written as \u escapes those pass the table, and the browser types the
    # characters the code evaluates to
    # dots and parentheses are escaped too: the harness splits the code into calls at dots outside
    # parentheses and ends the text at the first quote-paren
    literal = "".join(_escape(char) for char in act.text)
    return f'{target}.fill("{literal}")'


def _escape(char: str) -> str:
    if char.isascii() and char.isprintable() and char not in '"\\.()':
        return char
    return f"\\u{ord(char):04x}" if ord(char) < 0x10000 else f"\\U{ord(char):08x}"


def _render_select(act: Select) -> str:
    _check_text(act.option, "select option")
    return f"{act.locator.render()}.select_option({_literal(act.option)})"


def _render_stop(act: Stop) -> str:
    if act.answer == "":
        raise InvalidAction("the harness cannot parse an empty stop; use NO_ANSWER")
    _check_text(act.answer, "stop answer")
    return f'page.stop("{act.answer}")'


_RENDER: dict[type, Callable[[Any], str]] = {
    Goto: lambda a: f"page.goto({_literal(a.url)})",
    Click: lambda a: f"{a.locator.render()}.click()",
    Type: _render_type,
    Select: _render_select,
    Check: lambda a: f"{a.locator.render()}.check()",
    Hover: lambda a: f"{a.locator.render()}.hover()",
    Press: lambda a: f"page.press({_literal(a.key)})",
    Scroll: lambda a: f"page.scroll({a.direction})",
    Stop: _render_stop,
    Focus: lambda a: f"page.page_focus({a.tab})",
}


def render(act: Act) -> str:
    return _RENDER[type(act)](act)


def to_harness(act: Act) -> dict[str, Any]:
    code = render(act)
    if isinstance(act, Stop):
        action: dict[str, Any] = create_stop_action(act.answer)
        action["pw_code"] = code
        action["raw_prediction"] = code
        return action
    try:
        action = create_playwright_action(code)
        if isinstance(act, _LOCATOR_ACTS):
            parse_playwright_code(code)
    except (ValueError, SyntaxError) as e:
        raise InvalidAction(f"{code}: {e}") from e
    # the harness gives Playwright-coded actions the role id of "link", so its is_equivalent
    # compares role and empty name and calls every two clicks, or every two types, the same
    # action; with the role cleared, execution and equivalence both use the code string
    if isinstance(act, _LOCATOR_ACTS):
        action["element_role"] = 0
    action["pw_code"] = code
    action["raw_prediction"] = code
    return action
