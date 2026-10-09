import pytest

from lk47.skills.common import Precondition
from lk47.skills.shopping_admin.catalog import classify_product
from lk47.skills.shopping_admin.rules import _discount


@pytest.mark.parametrize(
    ("rule", "action", "amount"),
    [
        ("a 20 percent discount site-wide", "Percent of product price discount", "20"),
        ("45% off on all products", "Percent of product price discount", "45"),
        ("$10 discount on checkout", "Fixed amount discount for whole cart", "10"),
        ("$40 discount on checkout", "Fixed amount discount for whole cart", "40"),
    ],
)
def test_discount_phrases(rule: str, action: str, amount: str) -> None:
    assert _discount(rule) == (action, amount)


def test_discount_without_amount_is_a_precondition_failure() -> None:
    with pytest.raises(Precondition):
        _discount("free shipping for everyone")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Energy-Bulk Women Shirt", ("Top", "Tops", "Women")),
        ("Energy-Bulk Man Yoga Pant", ("Bottom", "Bottoms", "Men")),
        ("FancyBoy Man Causal Jeans", ("Bottom", "Bottoms", "Men")),
        ("Swaatch Smart Watch", ("Gear", "Watches", None)),
        ("Lelelumon Yoga Mat", ("Gear", "Fitness Equipment", None)),
    ],
)
def test_classify_product(name: str, expected: tuple[str, str, str | None]) -> None:
    assert classify_product(name) == expected


def test_matrix_rows_and_wanted_combinations() -> None:
    from pathlib import Path

    import lxml.html

    from lk47.skills.shopping_admin.catalog import Combo, _wanted, parse_matrix
    from lk47.snapshot import PageSnapshot

    html = (Path(__file__).parent / "fixtures/shopping_admin/product_edit_1130.html").read_text()
    existing, price, quantity = parse_matrix(PageSnapshot("fixture", html, "", 1, lxml.html.fromstring(html)))
    assert len(existing) == 15 and (price, quantity) == ("59.00", "100")
    assert existing[0] == Combo("XS", "Gray")
    assert _wanted("color", "brown", "size S", existing) == {Combo("S", "Brown")}
    assert _wanted("color", "blue", "size S and M", existing) == {Combo("S", "Blue"), Combo("M", "Blue")}
    assert _wanted("size", "30 and 31", "all color variants", existing) == {
        Combo(s, c) for s in ("30", "31") for c in ("Gray", "Purple", "White")
    }
    assert _wanted("size", "XXS", "blue and purple", existing) == {Combo("XXS", "Blue"), Combo("XXS", "Purple")}
