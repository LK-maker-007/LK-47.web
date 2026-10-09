import os
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Goto
from lk47.skills.shopping_admin.customers import customer_by_phone, parse_customers
from lk47.skills.shopping_admin.grid import records_found
from lk47.skills.shopping_admin.reviews import (
    count_by_status,
    delete_reviews,
    parse_reviews,
    parse_stars,
    product_words,
)
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/shopping_admin"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


def test_reviews_grid_parses_rows_and_total() -> None:
    snap = snapshot("reviews_grid.html")
    rows = parse_reviews(snap)
    assert records_found(snap) == 351
    assert len(rows) == 20
    assert rows[0].review_id == 353 and rows[0].nickname == "Hannah Lim" and rows[0].status == "Pending"
    assert rows[0].product == "Circe Hooded Ice Fleece"


def test_review_edit_page_gives_one_star_for_the_lowest_radio() -> None:
    assert parse_stars(snapshot("review_edit_353.html")) == 1


def test_product_words_drop_stopwords_and_plurals() -> None:
    assert product_words("Circe fleece") == ["circe", "fleece"]
    assert product_words("the style of Zoe product") == ["zoe"]
    assert product_words("tanks products") == ["tank"]


def test_customers_grid_parses_every_customer() -> None:
    rows = parse_customers(snapshot("customers_grid.html"))
    assert len(rows) == 70
    assert any(r.name == "Hannah Lim" and r.email == "hannah.lim@gmail.com" for r in rows)


def test_customer_by_phone_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = customer_by_phone("+1 2058812302")
    first = next(skill)
    assert isinstance(first, Goto) and first.url.endswith("/customer/index/")
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("customers_grid.html"))
    assert done.value.value == "John Smith, john.smith.xyz@gmail.com"


def test_count_by_status_uses_the_status_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = count_by_status("Not Approved")
    first = next(skill)
    assert isinstance(first, Goto) and "/review/product/index/limit/200/page/1/filter/" in first.url
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("reviews_grid.html"))
    assert done.value.value == "351"


def test_delete_reviews_reads_the_criteria(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING_ADMIN", "http://admin.invalid/admin")
    skill = delete_reviews("pending reviews with less than 4 stars")
    first = next(skill)
    assert isinstance(first, Goto)
    import base64

    token = first.url.rsplit("/filter/", 1)[1].strip("/")
    assert base64.b64decode(token).decode() == "status=2"


def test_author_is_read_from_the_review_page() -> None:
    from lk47.skills.shopping_admin.reviews import author

    assert author(snapshot("review_edit_351.html", 1)) == ("Emma Lopez", "emma.lopez@gmail.com")
    assert author(snapshot("review_edit_353.html", 1)) == (None, None)


def test_product_words_drop_possessives_and_plurals() -> None:
    assert product_words("Circe's products") == ["circe"]
    assert product_words("Olivia zip jacket") == ["olivia", "zip", "jacket"]
    assert product_words("tanks products") == ["tank"]
