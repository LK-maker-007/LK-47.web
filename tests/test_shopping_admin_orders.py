import os
from decimal import Decimal
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Click, Goto
from lk47.skills.shopping_admin.orders import (
    normalize_status,
    order_attribute,
    parse_order_view,
    parse_orders,
    total_payment,
    with_status,
)
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/shopping_admin"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


def test_orders_grid_rows() -> None:
    rows = parse_orders(snapshot("orders_grid.html"))
    assert len(rows) == 200
    newest = max(rows, key=lambda r: r.purchased)
    assert newest.order_id == "000000299" and newest.status == "Pending"
    assert newest.grand_total == Decimal("219.40") and newest.bill_to == "Sarah Miller"
    assert {r.status for r in rows} <= {"Canceled", "Complete", "Pending", "Processing"}


def test_order_view_fields_and_items() -> None:
    view = parse_order_view(snapshot("order_view_299.html"))
    assert view.order_id == "000000299"
    assert view.customer_name == "Sarah Miller" and view.email == "helloworld@yahoo.com"
    assert view.status == "Pending"
    assert view.grand_total == Decimal("219.40") and view.subtotal == Decimal("243.00")
    assert len(view.items) == 5
    assert view.items[0].name == "Argus All-Weather Tank" and view.items[0].quantity == 1
    assert view.items[0].sku == "MT07-M-Gray"
    assert sum(i.quantity for i in view.items) == 5
    assert sum(i.row_total for i in view.items) == view.subtotal


@pytest.mark.parametrize(
    ("phrase", "status"),
    [("most recent canlled", "Canceled"), ("newest pending", "Pending"), ("oldest complete", "Complete"), ("earliest fraud suspect", "Suspected Fraud")],
)
def test_status_phrases(phrase: str, status: str) -> None:
    assert normalize_status(phrase) == status


def test_non_cancelled_keeps_every_other_status() -> None:
    rows = parse_orders(snapshot("orders_grid.html"))
    assert all(r.status != "Canceled" for r in with_status(rows, "non-cancelled"))


def test_total_payment_replay_sums_the_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = total_payment("2", "pending")
    assert isinstance(next(skill), Goto)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("orders_grid.html"))
    rows = sorted(parse_orders(snapshot("orders_grid.html")), key=lambda r: r.purchased, reverse=True)
    expected = sum(r.grand_total for r in [r for r in rows if r.status == "Pending"][:2])
    assert done.value.value == f"{expected:.2f}"


def test_order_attribute_opens_the_newest_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = order_attribute("customer name", "newest pending")
    assert isinstance(next(skill), Goto)
    second = skill.send(snapshot("orders_grid.html"))
    assert isinstance(second, Goto) and second.url.endswith("/sales/order/view/order_id/299/")
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("order_view_299.html", 2))
    assert done.value.value == "Sarah Miller"
    assert not isinstance(second, Click)
