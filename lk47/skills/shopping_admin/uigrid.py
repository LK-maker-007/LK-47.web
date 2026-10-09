from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from lk47.actions import Click, Goto, Hover, Locator, Press, Type
from lk47.sites import site_url
from lk47.skills.common import Postcondition, Skill, settle
from lk47.skills.forms import choose_option
from lk47.snapshot import PageSnapshot

# UI-component grids (products, orders, customers, invoices, CMS pages) render their rows
# after the page loads and remember keyword, filters and current page per admin user
# across loads; every opener below starts from a cleared grid
ROWS = ".admin__data-grid-wrap tbody tr.data-row"
HEADER = ".admin__data-grid-header"
CHIPS = ".admin__current-filters-list"
EDIT_ID = re.compile(r"/(?:edit|view)/(?:id|page_id|order_id|invoice_id)/(\d+)/")


@dataclass(frozen=True)
class GridRow:
    cells: tuple[str, ...]
    link_id: int | None


def grid_rows(snapshot: PageSnapshot) -> list[GridRow]:
    rows = []
    for tr in snapshot.css(ROWS):
        cells = tuple(" ".join(td.text_content().split()) for td in tr.cssselect("td"))
        ids = [m.group(1) for a in tr.cssselect("a") if (m := EDIT_ID.search(a.get("href") or ""))]
        rows.append(GridRow(cells, int(ids[0]) if ids else None))
    return rows


def has_filters(snapshot: PageSnapshot) -> bool:
    return any(e.text_content().strip() for e in snapshot.css(CHIPS))


def header_button(label: str) -> Locator:
    return Locator.css(f"{HEADER} button").having_text(label)


# the sticky header repeats the grid's filter buttons, and "Filters" is also part of "Apply
# Filters", so the buttons are named by their action and the first copy is taken
OPEN_FILTERS = Locator.css("button[data-action='grid-filter-expand']").nth(0)
APPLY_FILTERS = Locator.css("button[data-action='grid-filter-apply']").nth(0)


def open_grid(path: str) -> Skill[PageSnapshot]:
    snapshot = yield Goto(f"{site_url('SHOPPING_ADMIN')}/{path}")
    if has_filters(snapshot):
        yield Click(header_button("Clear all"))
        snapshot = yield Hover(Locator.css("body"))
    if not snapshot.css(ROWS):
        snapshot = yield Hover(Locator.css("body"))
    return snapshot


def search(keyword: str) -> Skill[PageSnapshot]:
    yield Type(Locator.css("input#fulltext").nth(0), keyword)
    snapshot = yield Press("Enter")
    if not snapshot.css(ROWS) and "0 records" not in " ".join(snapshot.html.split()):
        snapshot = yield Hover(Locator.css("body"))
    return snapshot


def apply_filters(texts: Mapping[str, str], selects: Mapping[str, str]) -> Skill[PageSnapshot]:
    # text fields by input name; selects by the text of their field block, because a name such
    # as type_id cannot appear in a fill (lk47.actions._render_type) and the select's aria-label
    # hides its visible label from get_by_label
    yield Click(OPEN_FILTERS)
    panel = ".admin__data-grid-filters"
    for name, value in texts.items():
        yield Type(Locator.css(f"{panel} input[name='{name}']"), value)
    for field, label in selects.items():
        block = Locator.css(f"{panel} .admin__form-field").having_text(field)
        yield from choose_option(block.inside("select"), label)
    snapshot = yield Click(APPLY_FILTERS)
    for n in range(3):
        if has_filters(snapshot):
            return snapshot
        snapshot = yield settle(n)
    raise Postcondition(f"filters not applied at {snapshot.url}")


def next_page() -> Skill[PageSnapshot]:
    return (yield Click(Locator.css(".admin__data-grid-pager button.action-next").nth(0)))


def previous_page() -> Skill[PageSnapshot]:
    return (yield Click(Locator.css(".admin__data-grid-pager button.action-previous").nth(0)))
