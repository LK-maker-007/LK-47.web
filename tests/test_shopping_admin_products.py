import os
from decimal import Decimal
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Act, Click, Goto, Hover, Press, Type
from lk47.skills.shopping_admin.products import (
    EVERY_SIZE,
    ProductRow,
    adjust,
    catalog_product,
    children,
    find_products,
    low_units,
    matches,
    parse_products,
    parse_spec,
    same_word,
)
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/shopping_admin"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


def test_products_grid_rows_carry_ids_prices_and_quantities() -> None:
    rows = parse_products(snapshot("products_grid_hollister.html"))
    assert len(rows) == 16
    parent = next(r for r in rows if r.kind == "Configurable Product")
    assert parent.product_id == 126 and parent.name == "Hollister Backyard Sweatshirt"
    assert parent.price is None and parent.variant is None
    child = next(r for r in rows if r.sku == "MH05-XS-Red")
    assert child.product_id == 112 and child.price == Decimal("52.00") and child.quantity == 100
    assert child.variant == ("XS", "Red") and child.base_name == "Hollister Backyard Sweatshirt"


@pytest.mark.parametrize(
    ("phrase", "words", "color", "sizes"),
    [
        ("green Hollister backyard sweater in all size", ("Hollister", "backyard", "sweater"), "Green", EVERY_SIZE),
        ("size 28 Sahara leggings", ("Sahara", "leggings"), None, ("28",)),
        ("yellow shirts from Gwyn Endurance in all size below L", ("shirts", "Gwyn", "Endurance"), "Yellow", ("XS", "S", "M")),
        ("white Ingrid Running with size L and above", ("Ingrid", "Running"), "White", ("L", "XL")),
        ("black fitness tshirts from Desiree with size XS", ("fitness", "tshirts", "Desiree"), "Black", ("XS",)),
        ("all blue running tshirts in extra small and small sizes", ("running", "tshirts"), "Blue", ("XS", "S")),
        ("blue Cronus yoga pants with size 33", ("Cronus", "yoga", "pants"), "Blue", ("33",)),
        ("brown Aero daily fitness tee in every size", ("Aero", "daily", "fitness", "tee"), "Brown", EVERY_SIZE),
        ("Teton pullover hoodie", ("Teton", "pullover", "hoodie"), None, None),
        ("Minerva LumaTech V-Tee", ("Minerva", "LumaTech", "V", "Tee"), None, None),
        ("Circe's hooded ice fleece", ("Circe", "hooded", "ice", "fleece"), None, None),
    ],
)
def test_phrases_split_into_words_color_and_sizes(phrase: str, words: tuple[str, ...], color: str | None, sizes: tuple[str, ...] | None) -> None:
    spec = parse_spec(phrase)
    assert (spec.words, spec.color, spec.sizes) == (words, color, sizes)


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("pants", "Pant", True),
        ("sweater", "Sweatshirt", True),
        ("lHelios", "Helios", True),
        ("Aeno", "Aeon", True),
        ("hoodie", "Hoodlie", True),
        ("tshirts", "Tee", False),
        ("running", "Runway", False),
        ("tank", "Tee", False),
    ],
)
def test_word_matching_tolerates_catalog_spellings(a: str, b: str, same: bool) -> None:
    assert same_word(a, b) is same


def test_children_pick_the_colour_in_every_size() -> None:
    rows = parse_products(snapshot("products_grid_hollister.html"))
    spec = parse_spec("green Hollister backyard sweater in all size")
    found = children(rows, spec)
    assert sorted(r.product_id for r in found) == [111, 114, 117, 120, 123]
    assert {r.variant[1] for r in found if r.variant} == {"Green"}


def test_catalog_product_prefers_the_configurable_parent() -> None:
    rows = parse_products(snapshot("products_grid_hollister.html"))
    assert catalog_product(rows, parse_spec("Hollister backyard sweater")).product_id == 126


def test_a_proper_name_must_match() -> None:
    row = ProductRow(1, "Helios Endurance Tank", "Configurable Product", "MT04", None, None, "Enabled")
    assert matches(row, parse_spec("lHelios Endurance Tank"))
    assert not matches(row, parse_spec("Gwyn Endurance Tank"))


@pytest.mark.parametrize(
    ("price", "action", "amount", "expected"),
    [
        ("32.00", "Reduce", "$5", "27.00"),
        ("69.00", "Reduce", "10%", "62.10"),
        ("45.00", "Reduce", "15%", "38.25"),
        ("18.00", "Increase", "$11.5", "29.50"),
        ("32.00", "Increase", "15%", "36.80"),
        ("75.00", "Reduce", "13.5%", "64.88"),
        ("24.00", "Increase", "37%", "32.88"),
    ],
)
def test_price_arithmetic_rounds_half_up(price: str, action: str, amount: str, expected: str) -> None:
    from lk47.skills.shopping_admin.products import money

    assert money(adjust(Decimal(price), action, amount)) == expected


def test_find_products_searches_the_proper_name_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = find_products(["Hollister", "backyard", "sweater"])
    first = next(skill)
    assert isinstance(first, Goto) and first.url.endswith("/catalog/product/")
    second = skill.send(snapshot("products_grid_qty_1_3.html"))
    assert isinstance(second, Click) and "Clear all" in second.locator.render()
    assert isinstance(skill.send(snapshot("products_grid_hollister.html")), Hover)
    third = skill.send(snapshot("products_grid_hollister.html"))
    assert isinstance(third, Type) and third.text == "Hollister"
    fourth = skill.send(snapshot("products_grid_hollister.html"))
    assert isinstance(fourth, Press)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("products_grid_hollister.html", 2))
    assert len(done.value.value) == 16


def test_low_units_answers_from_the_filtered_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = low_units("product names and the sizes", "2-3")
    acts: list[Act] = [next(skill)]
    grid = snapshot("report_sales_form.html")  # no filters and no rows yet: the hover retry fires
    acts.append(skill.send(grid))
    assert isinstance(acts[-1], Hover)
    plain = snapshot("cms_pages_grid.html")
    acts.append(skill.send(plain))
    assert isinstance(acts[-1], Click) and "grid-filter-expand" in acts[-1].locator.render()
    for _ in range(3):
        acts.append(skill.send(plain))
    assert [a.text for a in acts[-3:] if isinstance(a, Type)] == ["2", "3", "Simple Product"]
    apply = skill.send(plain)
    assert isinstance(apply, Click) and "grid-filter-apply" in apply.locator.render()
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("products_grid_qty_1_3.html", 2))
    assert done.value.value == "Eos V-Neck Hoodie: S, Minerva LumaTech™ V-Tee: XS"
