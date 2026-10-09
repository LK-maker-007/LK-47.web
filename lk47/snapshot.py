from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import lxml.html
from lxml.html import HtmlElement


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    html: str
    fail_error: str
    step: int
    tree: HtmlElement | None
    tabs: tuple[str, ...] = ()

    @classmethod
    def from_state(cls, state: Mapping[str, Any], step: int) -> PageSnapshot:
        page = state["info"]["page"]
        html: str = page.content
        tree = lxml.html.fromstring(html) if html.strip() else None
        text = state.get("observation", {}).get("text", "")
        return cls(
            page.url, html, state["info"].get("fail_error", ""), step, tree, tab_titles(text)
        )

    def css(self, selector: str) -> list[HtmlElement]:
        if self.tree is None:
            return []
        return list(self.tree.cssselect(selector))

    def text(self, selector: str) -> str | None:
        found = self.css(selector)
        if not found:
            return None
        return " ".join(found[0].text_content().split())

    def value(self, selector: str) -> str | None:
        found = self.css(selector)
        if not found:
            return None
        value = found[0].get("value")
        return value if isinstance(value, str) else None


def tab_titles(observation: str) -> tuple[str, ...]:
    # "Tab 0 (current): Title | Tab 1: Title" heads the harness's text observation
    head = observation.split("\n", 1)[0]
    if not head.startswith("Tab "):
        return ()
    return tuple(part.split(":", 1)[1].strip() for part in head.split(" | ") if ":" in part)
