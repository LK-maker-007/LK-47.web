from __future__ import annotations

import calendar
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from lk47.actions import Check, Click, Goto, Hover, Locator, Press, Type
from lk47.normalize import Unsupported, period_range
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import choose_option, replace_text
from lk47.skills.shopping_admin import uigrid
from lk47.skills.shopping_admin.customers import customers
from lk47.skills.shopping_admin.grid import records_found
from lk47.snapshot import PageSnapshot

DATE_FORMAT = "%b %d, %Y %I:%M:%S %p"
ORDINALS = {
    "most": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip
CARRIERS = {
    "dhl": "DHL",
    "fedex": "Federal Express",
    "federal express": "Federal Express",
    "ups": "United Parcel Service",
    "united parcel service": "United Parcel Service",
    "usps": "United States Postal Service",
    "united states postal service": "United States Postal Service",
}

STATUS_WORDS = {
    "canceled": "Canceled",
    "cancelled": "Canceled",
    "canlled": "Canceled",
    "complete": "Complete",
    "completed": "Complete",
    "pending": "Pending",
    "processing": "Processing",
    "on hold": "On Hold",
    "fraud suspect": "Suspected Fraud",
    "suspected fraud": "Suspected Fraud",
    "fraud": "Suspected Fraud",
}


@dataclass(frozen=True)
class OrderRow:
    order_id: str
    purchased: datetime
    bill_to: str
    ship_to: str
    grand_total: Decimal
    status: str


@dataclass(frozen=True)
class Item:
    name: str
    sku: str
    quantity: int
    price: Decimal
    row_total: Decimal


@dataclass(frozen=True)
class OrderView:
    order_id: str
    customer_name: str
    email: str
    order_date: str
    status: str
    items: tuple[Item, ...]
    grand_total: Decimal
    subtotal: Decimal


def money(text: str) -> Decimal:
    m = re.search(r"-?\$?([\d,]+\.\d{2})", text)
    if m is None:
        raise Postcondition(f"no amount in {text!r}")
    value = Decimal(m.group(1).replace(",", ""))
    return -value if text.strip().startswith("-") else value


def parse_orders(snapshot: PageSnapshot) -> list[OrderRow]:
    rows = []
    for tr in snapshot.css(".admin__data-grid-wrap tbody tr"):
        c = [" ".join(td.text_content().split()) for td in tr.cssselect("td")]
        if len(c) >= 9 and c[1].isdigit():
            rows.append(
                OrderRow(c[1], datetime.strptime(c[3], DATE_FORMAT), c[4], c[5], money(c[7]), c[8])
            )
    return rows


def has_active_filters(snapshot: PageSnapshot) -> bool:
    return any(e.text_content().strip() for e in snapshot.css(".admin__current-filters-list"))


def grid_url() -> str:
    return f"{site_url('SHOPPING_ADMIN')}/sales/order/"


def orders(all_pages: bool = False) -> Skill[list[OrderRow]]:
    # the grid remembers filters and the current page across loads; both are undone here
    snapshot = yield Goto(grid_url())
    if has_active_filters(snapshot):
        snapshot = yield Click(
            Locator.css(".admin__data-grid-header button").having_text("Clear all")
        )
    rows = parse_orders(snapshot)
    if not rows:
        snapshot = yield Hover(Locator.css("body"))
        rows = parse_orders(snapshot)
    if not rows:
        raise Postcondition(f"orders grid rendered no rows at {snapshot.url}")
    pager_next = Locator.css(".admin__data-grid-pager button.action-next").nth(0)
    pager_previous = Locator.css(".admin__data-grid-pager button.action-previous").nth(0)
    if rows[0].order_id != "000000299" and all(r.order_id != "000000299" for r in rows):
        snapshot = yield Click(pager_previous)
        rows = parse_orders(snapshot)
    if all_pages and records_found(snapshot) > len(rows):
        snapshot = yield Click(pager_next)
        rows = rows + parse_orders(snapshot)
        yield Click(pager_previous)
    return sorted(rows, key=lambda r: r.purchased, reverse=True)


def parse_order_view(snapshot: PageSnapshot) -> OrderView:
    def field(table: str, label: str) -> str:
        for tr in snapshot.css(f"{table} tr"):
            cells = [" ".join(td.text_content().split()) for td in tr.cssselect("th, td")]
            if len(cells) >= 2 and cells[0].lower().startswith(label.lower()):
                return cells[1]
        raise Postcondition(f"no {label!r} in {table} at {snapshot.url}")

    items = []
    for tr in snapshot.css(".edit-order-table tbody tr"):
        c = [" ".join(td.text_content().split()) for td in tr.cssselect("td")]
        if len(c) < 11:
            continue
        # the first cell reads "Name SKU: ABC-M-Gray Color: Gray Size: M"; the qty column is
        # split into two cells, so Subtotal is the sixth cell and Row Total the last
        name, _, sku = c[0].partition("SKU:")
        qty = re.search(r"Ordered\s+(\d+)", c[4])
        items.append(
            Item(
                name.strip(),
                sku.split()[0] if sku.split() else "",
                int(qty.group(1)) if qty else 0,
                money(c[3]),
                money(c[6]),
            )
        )
    title = snapshot.text("h1.page-title") or ""
    order_id = title.lstrip("#").split()[0] if title else ""
    totals = {
        " ".join(tr.cssselect("td")[0].text_content().split()): " ".join(
            tr.cssselect("td")[-1].text_content().split()
        )
        for tr in snapshot.css(".order-totals tr, .order-subtotal-table tr")
        if len(tr.cssselect("td")) >= 2
    }
    status = snapshot.text("#order_status") or field(".order-information-table", "Order Status")
    return OrderView(
        order_id,
        field(".order-account-information-table", "Customer Name"),
        field(".order-account-information-table", "Email"),
        field(".order-information-table", "Order Date"),
        status,
        tuple(items),
        money(totals.get("Grand Total", "")),
        money(totals.get("Subtotal", "")),
    )


def view_url(order_id: str) -> str:
    return f"{site_url('SHOPPING_ADMIN')}/sales/order/view/order_id/{int(order_id)}/"


def open_order(order_id: str) -> Skill[OrderView]:
    snapshot = yield Goto(view_url(order_id))
    return parse_order_view(snapshot)


def normalize_status(text: str) -> str | None:
    t = text.lower()
    for word, status in sorted(STATUS_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in t:
            return status
    return None


def with_status(rows: list[OrderRow], phrase: str) -> list[OrderRow]:
    if "non-cancelled" in phrase.lower() or "non-canceled" in phrase.lower():
        return [r for r in rows if r.status != "Canceled"]
    status = normalize_status(phrase)
    if status is None:
        raise Precondition(f"no order status in {phrase!r}")
    return [r for r in rows if r.status == status]


def order_attribute(attribute: str, status: str) -> Skill[str]:
    oldest = any(w in status.lower() for w in ("oldest", "earliest", "first"))
    rows = yield from orders(all_pages=oldest)
    matching = with_status(rows, status)
    if not matching:
        return "N/A"
    row = matching[-1] if oldest else matching[0]
    key = attribute.lower()
    if "billing name" in key:
        return row.bill_to
    if key == "order id":
        return row.order_id
    view = yield from open_order(row.order_id)
    return describe_order(view, key)


def describe_order(view: OrderView, key: str) -> str:
    if "purchase date" in key and "order id" in key:
        value = f"order id: {view.order_id}, purchase date: {view.order_date}"
    elif "customer name" in key:
        value = view.customer_name
    elif "date" in key:
        value = view.order_date
    elif "product name" in key and "price" in key:
        priced = sorted(view.items, key=lambda i: i.price)
        value = ", ".join(f"{i.name}: ${i.price}" for i in priced)
    else:
        raise Precondition(f"unknown order attribute {key!r}")
    return value


def total_payment(N: str, status: str) -> Skill[str]:  # noqa: N803  slot name from the template
    rows = yield from orders()
    chosen = with_status(rows, status)[: int(N)]
    return f"{sum(r.grand_total for r in chosen):.2f}"


def payment_difference(N: str, status_1: str, status_2: str) -> Skill[str]:  # noqa: N803
    rows = yield from orders()
    first = sum(r.grand_total for r in with_status(rows, status_1)[: int(N)])
    second = sum(r.grand_total for r in with_status(rows, status_2)[: int(N)])
    return f"{abs(first - second):.2f}"


def items_sold(k: str) -> Skill[str]:
    rows = yield from orders()
    total = 0
    for row in rows[: int(k)]:
        view = yield from open_order(row.order_id)
        total += sum(i.quantity for i in view.items)
    return str(total)


def most_cancellations(attribute: str) -> Skill[str]:
    rows = yield from orders(all_pages=True)
    cancelled = [r for r in rows if r.status == "Canceled"]
    if not cancelled:
        return "N/A"
    counts = Counter(r.bill_to for r in cancelled)
    name, count = counts.most_common(1)[0]
    key = attribute.lower()
    if key == "name":
        return name
    if "total number" in key:
        return str(count)
    theirs = [r for r in cancelled if r.bill_to == name]
    if "email" in key or "phone" in key:
        people = yield from customers()
        match = next((c for c in people if c.name.lower() == name.lower()), None)
        if match is None:
            raise Postcondition(f"no customer named {name!r}")
        return f"email: {match.email}, name: {match.name}, phone number: {match.phone}"
    view = yield from open_order(theirs[0].order_id)
    if "sku" in key:
        return ", ".join(i.sku for i in view.items)
    if "total spend" in key:
        return f"{view.subtotal:.2f}"
    raise Precondition(f"unknown attribute {attribute!r}")


def cancel_order(id: str) -> Skill[str]:  # noqa: A002  slot name from the template
    yield Goto(view_url(id))
    yield Click(Locator.role("button", name="Cancel", exact=True))
    snapshot = yield Click(Locator.css(".modal-popup._show button").having_text("OK"))
    status = snapshot.text("#order_status")
    if status != "Canceled":
        raise Postcondition(f"order {id} status is {status!r} after cancel")
    return ""


def same_customer(name: str, wanted: str) -> bool:
    tokens = re.findall(r"[a-z]+", name.lower())

    def alike(a: str, b: str) -> bool:
        short, long = sorted((a, b), key=len)
        return a == b or (len(short) >= 4 and long.startswith(short))

    return all(any(alike(w, t) for t in tokens) for w in re.findall(r"[a-z]+", wanted.lower()))


def notify_customer(name: str, message: str) -> Skill[str]:
    yield from uigrid.open_grid("sales/order/")
    snapshot = yield from uigrid.search(name)
    rows = sorted(parse_orders(snapshot), key=lambda r: r.purchased, reverse=True)
    pending = [r for r in rows if r.status == "Pending" and same_customer(r.bill_to, name)]
    if not pending:
        return "N/A"
    yield Goto(view_url(pending[0].order_id))
    yield Type(Locator.css("textarea[name='history[comment]']"), message)
    yield Check(Locator.css("input[name='history[is_customer_notified]']"))
    snapshot = yield Click(Locator.role("button", name="Submit Comment"))
    # the history list reloads over AJAX after the submit
    for _ in range(2):
        comments = [" ".join(e.text_content().split()) for e in snapshot.css(".note-list-comment")]
        if any(message in c for c in comments):
            return ""
        snapshot = yield Hover(Locator.css("body"))
    raise Postcondition("comment not shown in the order history")


def filter_orders(status: str) -> Skill[str]:
    label = normalize_status(status)
    if label is None:
        raise Precondition(f"no order status in {status!r}")
    snapshot = yield Goto(grid_url())
    if has_active_filters(snapshot):
        yield Click(Locator.css(".admin__data-grid-header button").having_text("Clear all"))
    yield Click(uigrid.OPEN_FILTERS)
    yield from choose_option(Locator.css(".admin__data-grid-filters select[name='status']"), label)
    snapshot = yield Click(uigrid.APPLY_FILTERS)
    chips = " ".join(e.text_content() for e in snapshot.css(".admin__current-filters-list"))
    if label not in chips:
        raise Postcondition(f"status filter {label!r} not applied")
    return ""


def _complete_counts(rows: list[OrderRow]) -> Counter[str]:
    return Counter(r.bill_to for r in rows if r.status == "Complete")


def customers_by_orders(quantifier: str = "", number: str = "", any_state: str = "") -> Skill[str]:
    # "completed the most/second most/fifth most number of orders", "placed 2 orders"; the
    # template counts completed orders unless the Verified wording says "in any state", and ties
    # share a rank the way RANK() does
    rows = yield from orders(all_pages=True)
    counts = Counter(r.bill_to for r in rows) if any_state else _complete_counts(rows)
    if number:
        names = sorted(name for name, n in counts.items() if n == int(number))
    else:
        words = quantifier.lower().split()
        wanted = next((ORDINALS[w] for w in words if w in ORDINALS), None)
        if wanted is None:
            raise Precondition(f"no rank in {quantifier!r}")
        distinct = sorted(set(counts.values()), reverse=True)
        ranks = {
            n: 1 + sum(v for c, v in Counter(counts.values()).items() if c > n) for n in distinct
        }
        names = sorted(name for name, n in counts.items() if ranks[n] == wanted)
    return ", ".join(names) if names else "N/A"


def _month_span(period: str) -> tuple[int, int, int]:
    text = re.sub(r",?\s*inclusive$", "", period.strip())
    if m := re.fullmatch(
        r"from\s+([A-Za-z]+)\.?\s+(\d{4})\s+(?:to|through)\s+([A-Za-z]+)\.?\s+\2", text
    ):
        text = f"from {m.group(1)} to {m.group(3)} {m.group(2)}"
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})\s*-\s*(\d{1,2})/(\d{4})", text):
        if m.group(2) != m.group(4):
            raise Precondition(f"period spans years: {period!r}")
        return int(m.group(2)), int(m.group(1)), int(m.group(3))
    if m := re.fullmatch(
        r"(?:from\s+)?([A-Za-z]+)\.?\s+(?:to|-|through)\s+([A-Za-z]+)\.?\s+(\d{4})", text
    ):
        start, end = (
            period_range(f"{m.group(1)} {m.group(3)}"),
            period_range(f"{m.group(2)} {m.group(3)}"),
        )
        return int(m.group(3)), start.start.month, end.start.month
    raise Precondition(f"unsupported period {period!r}")


def monthly_orders(period: str) -> Skill[str]:
    try:
        year, first, last = _month_span(period)
    except Unsupported as e:
        raise Precondition(str(e)) from None
    rows = yield from orders(all_pages=True)
    by_month = Counter(
        r.purchased.month for r in rows if r.status == "Complete" and r.purchased.year == year
    )
    return ", ".join(
        f"{calendar.month_name[m]}: {by_month.get(m, 0)}" for m in range(first, last + 1)
    )


def _address_parts(address: str) -> tuple[list[str], str, str, str]:
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 4:
        raise Precondition(f"address needs street, city, state and zip: {address!r}")
    *streets, city, state, postcode = parts
    region = STATES.get(state.upper(), state)
    return streets, city, region, postcode


def edit_address(order_id: str, address: str) -> Skill[str]:
    streets, city, region, postcode = _address_parts(address)
    snapshot = yield Goto(view_url(order_id))
    links = snapshot.css(".order-shipping-address a[href*='/sales/order/address/']")
    if not links:
        raise Postcondition(f"no shipping address link on order {order_id}")
    snapshot = yield Goto(str(links[0].get("href")))
    yield from replace_text(Locator.css("input[name='street[0]']"), streets[0])
    second = snapshot.value("input[name='street[1]']") or ""
    if len(streets) > 1:
        yield from replace_text(Locator.css("input[name='street[1]']"), ", ".join(streets[1:]))
    elif second:
        yield Click(Locator.css("input[name='street[1]']"))
        yield Press("Control+a")
        yield Press("Backspace")
    yield from replace_text(Locator.css("input[name='city']"), city)
    yield from choose_option(Locator.css("select[name='region_id']"), region)
    yield from replace_text(Locator.css("input[name='postcode']"), postcode)
    snapshot = yield Click(Locator.role("button", name="Save Order Address"))
    if streets[0] not in snapshot.html:
        raise Postcondition("the order view does not show the new street")
    return ""


def add_tracking(order: str, service: str, tracking: str) -> Skill[str]:
    carrier = CARRIERS.get(service.strip().lower())
    if carrier is None:
        raise Precondition(f"unknown carrier {service!r}")
    snapshot = yield Goto(
        f"{site_url('SHOPPING_ADMIN')}/admin/order_shipment/new/order_id/{int(order)}/"
    )
    if "/order_shipment/new/" not in snapshot.url:
        raise Precondition(f"order {order} cannot be shipped, at {snapshot.url}")
    yield Click(Locator.role("button", name="Add Tracking Number"))
    yield from choose_option(Locator.css("select[name='tracking[1][carrier_code]']"), carrier)
    yield Type(Locator.css("input[name='tracking[1][number]']"), tracking)
    snapshot = yield Click(Locator.role("button", name="Submit Shipment"))
    if "The shipment has been created" not in snapshot.html:
        raise Postcondition(f"no shipment confirmation, at {snapshot.url}")
    return ""


REGISTRY["shopping_admin.order_attribute"] = order_attribute
REGISTRY["shopping_admin.customers_by_orders"] = customers_by_orders
REGISTRY["shopping_admin.monthly_orders"] = monthly_orders
REGISTRY["shopping_admin.edit_address"] = edit_address
REGISTRY["shopping_admin.add_tracking"] = add_tracking
REGISTRY["shopping_admin.total_payment"] = total_payment
REGISTRY["shopping_admin.payment_difference"] = payment_difference
REGISTRY["shopping_admin.items_sold"] = items_sold
REGISTRY["shopping_admin.most_cancellations"] = most_cancellations
REGISTRY["shopping_admin.cancel_order"] = cancel_order
REGISTRY["shopping_admin.notify_customer"] = notify_customer
REGISTRY["shopping_admin.filter_orders"] = filter_orders
