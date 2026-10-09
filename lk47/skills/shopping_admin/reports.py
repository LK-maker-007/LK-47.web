from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from lk47.actions import Click, Goto, Locator, Type
from lk47.normalize import DateRange, Unsupported, parse_day, period_range, relative_range
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.shopping_admin.grid import grid_rows, report_filter_url
from lk47.snapshot import PageSnapshot

CHILD_SKU = re.compile(r"^[A-Z]{2,4}\d{2,3}-(.+)$")


@dataclass(frozen=True)
class SoldRow:
    product: str
    sku: str
    quantity: int


def parse_ordered_products(snapshot: PageSnapshot) -> list[SoldRow]:
    rows = [
        SoldRow(cells[-3], cells[-2], int(cells[-1].replace(",", "")))
        for cells in grid_rows(snapshot)
        if len(cells) >= 3 and cells[-1].replace(",", "").isdigit()
    ]
    if not rows:
        raise Postcondition(f"no ordered-product rows at {snapshot.url}")
    return rows


def parse_bestseller_names(snapshot: PageSnapshot) -> frozenset[str]:
    return frozenset(cells[-3] for cells in grid_rows(snapshot) if len(cells) >= 3)


def ordered_products(period: str) -> Skill[list[SoldRow]]:
    start, end = period_range(period).admin_dates()
    url = report_filter_url(
        "report_product/sold", report_from=start, report_to=end, report_period="year"
    )
    snapshot = yield Goto(url)
    return parse_ordered_products(snapshot)


def bestseller_names(period: str) -> Skill[frozenset[str]]:
    start, end = period_range(period).admin_dates()
    # day granularity lists the top five of every day, which names each sold child exactly
    url = report_filter_url(
        "report_sales/bestsellers", period_type="day", **{"from": start, "to": end}
    )
    snapshot = yield Goto(url)
    return parse_bestseller_names(snapshot)


def child_name(row: SoldRow, names: frozenset[str]) -> str:
    m = CHILD_SKU.match(row.sku)
    if m is None:
        return row.product
    suffix = m.group(1)
    exact = [
        n
        for n in names
        if n.startswith(row.product)
        and n.endswith("-" + suffix)
        and n[len(row.product) :].strip(" -") == suffix
    ]
    return exact[0] if len(exact) == 1 else f"{row.product}-{suffix}"


def top_products(n: str, period: str) -> Skill[str]:
    sold = yield from ordered_products(period)
    names = yield from bestseller_names(period)
    count = int(n)
    if count == 1:
        return child_name(sold[0], names)
    # the report is sorted by quantity; a top-n list includes every product tied with the n-th
    cutoff = sold[min(count, len(sold)) - 1].quantity
    picked: list[str] = []
    for row in sold:
        if row.quantity < cutoff:
            break
        name = child_name(row, names)
        if name not in picked:
            picked.append(name)
    return ", ".join(picked)


def _top_group(rows: list[SoldRow], key: str) -> str:
    totals: dict[str, int] = {}
    for row in rows:
        words = row.product.split()
        group = words[0] if key == "brand" else words[-1]
        totals[group] = totals.get(group, 0) + row.quantity
    return max(totals, key=lambda g: (totals[g], -list(totals).index(g)))


def top_brand(period: str) -> Skill[str]:
    rows = yield from ordered_products(period)
    return _top_group(rows, "brand")


def top_product_type(period: str) -> Skill[str]:
    rows = yield from ordered_products(period)
    return _top_group(rows, "type")


REPORT_PATHS = (
    ("refund", "report_sales/refunded"),
    ("tax", "report_sales/tax"),
    ("shipping", "report_sales/shipping"),
    ("coupon", "report_sales/coupons"),
    ("invoice", "report_sales/invoiced"),
    ("best", "report_sales/bestsellers"),
    ("view", "report_product/viewed"),
    ("order", "report_sales/sales"),
    ("sales", "report_sales/sales"),
)


def report_path(kind: str) -> str:
    text = kind.lower()
    for word, path in REPORT_PATHS:
        if word in text:
            return path
    raise Precondition(f"unknown report {kind!r}")


def _show_report(path: str, span: DateRange) -> Skill[str]:
    # the filter re-renders dates as M/d/yy once the report is shown, so they are typed that way
    start, end = span.short_dates()
    yield Goto(f"{site_url('SHOPPING_ADMIN')}/reports/{path}/")
    yield Type(Locator.css("#sales_report_from"), start)
    yield Type(Locator.css("#sales_report_to"), end)
    snapshot = yield Click(Locator.role("button", name="Show Report"))
    if f"/reports/{path}/filter/" not in snapshot.url:
        raise Postcondition(f"report not shown, at {snapshot.url}")
    return ""


def report_for_span(report: str, time_span: str, today: str) -> Skill[str]:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", today.strip())
    if m is None:
        raise Precondition(f"no date in {today!r}")
    anchor = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    try:
        span = relative_range(anchor, time_span)
    except Unsupported:
        raise Precondition(f"unsupported span {time_span!r}") from None
    return (yield from _show_report(report_path(report), span))


def report_between(type: str, start_date: str, end_date: str) -> Skill[str]:  # noqa: A002
    try:
        span = DateRange(parse_day(start_date), parse_day(end_date))
    except Unsupported as e:
        raise Precondition(f"unsupported date {e}") from None
    return (yield from _show_report(report_path(type), span))


REGISTRY["shopping_admin.report_for_span"] = report_for_span
REGISTRY["shopping_admin.report_between"] = report_between
REGISTRY["shopping_admin.top_products"] = top_products
REGISTRY["shopping_admin.top_brand"] = top_brand
REGISTRY["shopping_admin.top_product_type"] = top_product_type
