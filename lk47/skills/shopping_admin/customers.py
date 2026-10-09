from __future__ import annotations

import re
from dataclasses import dataclass

from lk47.actions import Click, Goto, Hover, Locator
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Skill
from lk47.snapshot import PageSnapshot


@dataclass(frozen=True)
class CustomerRow:
    name: str
    email: str
    group: str
    phone: str
    zip_code: str
    country: str
    state: str
    since: str


def parse_customers(snapshot: PageSnapshot) -> list[CustomerRow]:
    rows = []
    for tr in snapshot.css(".admin__data-grid-wrap tbody tr"):
        cells = [" ".join(td.text_content().split()) for td in tr.cssselect("td")]
        if len(cells) >= 9 and "@" in cells[2]:
            rows.append(CustomerRow(*cells[1:9]))
    return rows


def has_keyword_filter(snapshot: PageSnapshot) -> bool:
    return any(e.text_content().strip() for e in snapshot.css(".admin__current-filters-list"))


def customers() -> Skill[list[CustomerRow]]:
    # the grid loads its rows after the page, and remembers a keyword search across sessions
    snapshot = yield Goto(f"{site_url('SHOPPING_ADMIN')}/customer/index/")
    if has_keyword_filter(snapshot):
        snapshot = yield Click(
            Locator.css(".admin__data-grid-header button").having_text("Clear all")
        )
    for _ in range(2):
        rows = parse_customers(snapshot)
        if rows:
            return rows
        snapshot = yield Hover(Locator.css("body"))
    raise Postcondition(f"customers grid rendered no rows at {snapshot.url}")


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def customer_by_phone(PhoneNum: str) -> Skill[str]:  # noqa: N803  slot name from the template
    rows = yield from customers()
    wanted = digits(PhoneNum)[-10:]
    for row in rows:
        if digits(row.phone)[-10:] == wanted:
            return f"{row.name}, {row.email}"
    return "N/A"


def customer_email(name: str) -> Skill[str]:
    rows = yield from customers()
    words = [w.lower() for w in name.split() if w]
    for row in rows:
        if all(w in row.name.lower() for w in words):
            return row.email
    raise Postcondition(f"no customer named {name!r}")


REGISTRY["shopping_admin.customer_by_phone"] = customer_by_phone
