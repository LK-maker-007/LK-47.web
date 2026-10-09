import os
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Goto
from lk47.skills.shopping_admin.grid import report_filter_url
from lk47.skills.shopping_admin.reports import (
    child_name,
    parse_bestseller_names,
    parse_ordered_products,
    top_products,
)
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/shopping_admin"


def snapshot(name: str, step: int) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


def test_ordered_products_are_sorted_by_quantity() -> None:
    rows = parse_ordered_products(snapshot("ordered_products_2023.html", 1))
    assert len(rows) == 141
    assert rows[0].product == "Sprite Yoga Strap 6 foot" and rows[0].quantity == 4
    quantities = [r.quantity for r in rows]
    assert quantities == sorted(quantities, reverse=True)


def test_bestseller_day_report_names_children_exactly() -> None:
    names = parse_bestseller_names(snapshot("bestsellers_day2023.html", 1))
    assert len(names) == 113
    assert "Mach Street Sweatshirt -XL-Blue" in names
    assert "Ida Workout Parachute Pant-29-Purple" in names


def test_child_name_prefers_the_catalog_spelling() -> None:
    names = parse_bestseller_names(snapshot("bestsellers_day2023.html", 1))
    rows = {r.sku: r for r in parse_ordered_products(snapshot("ordered_products_2023.html", 1))}
    assert child_name(rows["MH10-XL-Blue"], names) == "Mach Street Sweatshirt -XL-Blue"
    assert child_name(rows["WP03-29-Purple"], names) == "Ida Workout Parachute Pant-29-Purple"
    assert child_name(rows["24-WG085"], names) == "Sprite Yoga Strap 6 foot"


def test_top_products_replay_lists_every_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = top_products("5", "2023")
    first = next(skill)
    assert isinstance(first, Goto) and "/report_product/sold/filter/" in first.url
    second = skill.send(snapshot("ordered_products_2023.html", 1))
    assert isinstance(second, Goto) and "/report_sales/bestsellers/filter/" in second.url
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("bestsellers_day2023.html", 2))
    answer = done.value.value
    for expected in (
        "Sprite Yoga Strap 6 foot",
        "Overnight Duffle",
        "Ida Workout Parachute Pant-29-Purple",
        "Hawkeye Yoga Short-32-Blue",
        "Sprite Stasis Ball 65 cm",
    ):
        assert expected in answer
    assert answer.count("Sprite Stasis Ball 65 cm") == 1


def test_top_one_is_the_first_row() -> None:
    skill = top_products("1", "2023")
    next(skill)
    skill.send(snapshot("ordered_products_2023.html", 1))
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("bestsellers_day2023.html", 2))
    assert done.value.value == "Sprite Yoga Strap 6 foot"


def test_filter_url_is_base64_of_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://localhost:7780/admin")
    url = report_filter_url("report_sales/bestsellers", period_type="year", **{"from": "1/1/2022", "to": "12/31/2022"})
    token = url.rsplit("/filter/", 1)[1].strip("/")
    import base64

    assert base64.b64decode(token).decode() == "period_type=year&from=1%2F1%2F2022&to=12%2F31%2F2022"
