import os
from collections.abc import Generator
from datetime import date
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Act, Click, Goto, Type
from lk47.normalize import parse_day, relative_range
from lk47.skills.shopping_admin.orders import (
    _address_parts,
    _month_span,
    customers_by_orders,
    monthly_orders,
)
from lk47.skills.shopping_admin.reports import report_between, report_for_span, report_path
from lk47.skills.shopping_admin.store import frequent_search_brands, invoice_total, top_search_terms
from lk47.skills.shopping_admin.uigrid import grid_rows, has_filters
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/shopping_admin"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


def test_ui_grid_rows_expose_ids_from_edit_links() -> None:
    rows = grid_rows(snapshot("cms_pages_grid.html"))
    assert [(r.link_id, r.cells[2]) for r in rows[:3]] == [(1, "404 Not Found"), (2, "Home Page"), (3, "Enable Cookies")]
    assert not has_filters(snapshot("cms_pages_grid.html"))
    assert has_filters(snapshot("products_grid_hollister.html"))


def test_dashboard_lists_popular_terms_with_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = top_search_terms("3")
    assert isinstance(next(skill), Goto)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("dashboard.html"))
    assert done.value.value == "hollister, Joust Bag, Antonia Racer Tank"
    skill = frequent_search_brands()
    next(skill)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("dashboard.html"))
    assert done.value.value == "Hollister, Joust, Antonia"


def test_invoice_total_reads_the_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = invoice_total("000000002")
    next(skill)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("invoices_grid.html"))
    assert done.value.value == "$39.64"


def _all_orders(skill: Generator[Act, PageSnapshot, str]) -> str:
    assert isinstance(next(skill), Goto)
    nxt = skill.send(snapshot("orders_grid.html"))
    assert isinstance(nxt, Click) and "action-next" in nxt.locator.render()
    prev = skill.send(snapshot("orders_grid_page2.html"))
    assert isinstance(prev, Click) and "action-previous" in prev.locator.render()
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("orders_grid.html", 3))
    return str(done.value.value)


@pytest.mark.parametrize(
    ("quantifier", "number", "expected"),
    [
        ("most", "", "Jane Smith"),
        ("second most", "", "Adam Garcia, Michael Nguyen, Sarah Miller"),
        ("fifth most", "", "Ava Brown, Jane Doe, John Smith, Matt Baker"),
        ("", "2", "Alexander Thomas, Brian Smith, Julia Williams, Lisa Green, Lisa Kim"),
    ],
)
def test_customers_ranked_by_completed_orders(monkeypatch: pytest.MonkeyPatch, quantifier: str, number: str, expected: str) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    assert _all_orders(customers_by_orders(quantifier, number)) == expected


def test_monthly_completed_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    answer = _all_orders(monthly_orders("from May to December 2022"))
    assert answer == "May: 8, June: 13, July: 9, August: 8, September: 10, October: 4, November: 5, December: 10"
    assert _all_orders(monthly_orders("01/2023-05/2023")) == "January: 12, February: 7, March: 5, April: 9, May: 5"
    assert _month_span("from Jan to Nov 2022") == (2022, 1, 11)


def test_address_parts_expand_the_state() -> None:
    assert _address_parts("456 Oak Avenue, Apartment 5B, New York, NY, 10001") == (["456 Oak Avenue", "Apartment 5B"], "New York", "New York", "10001")
    assert _address_parts("789 Pine Lane, San Francisco, CA, 94102") == (["789 Pine Lane"], "San Francisco", "California", "94102")


def test_report_dates_follow_the_filter_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    assert relative_range(date(2023, 3, 15), "over the last 45 days").short_dates() == ("1/29/23", "3/15/23")
    assert parse_day("beginning of May 2021") == date(2021, 5, 1)
    assert report_path("sales order report") == "report_sales/sales"
    assert report_path("refund report") == "report_sales/refunded"
    assert report_path("product view") == "report_product/viewed"
    assert report_path("best sellers") == "report_sales/bestsellers"
    skill = report_for_span("tax report", "for this year", "3/15/2023")
    first = next(skill)
    assert isinstance(first, Goto) and first.url.endswith("/reports/report_sales/tax/")
    form = snapshot("report_sales_form.html")
    typed = [skill.send(form), skill.send(form)]
    assert [t.text for t in typed if isinstance(t, Type)] == ["1/1/23", "12/31/23"]
    skill = report_between("shipping", "08/05/2022", "03/01/2023")
    next(skill)
    typed = [skill.send(form), skill.send(form)]
    assert [t.text for t in typed if isinstance(t, Type)] == ["8/5/22", "3/1/23"]


def test_theme_row_is_matched_on_its_first_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    from lk47.actions import render
    from lk47.skills.shopping_admin.store import theme_preview

    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = theme_preview("Magento Blank")
    assert isinstance(next(skill), Goto)
    click = skill.send(snapshot("themes_grid.html"))
    assert render(click) == (
        'page.locator("tr.data-row td:first-child").filter(has_text="Magento Blank").click()'
    )
