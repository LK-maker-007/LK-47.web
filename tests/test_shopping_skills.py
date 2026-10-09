import os
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Act, Goto, Type, render
from lk47.skills.shopping.account import coupon_request, refund_message
from lk47.skills.shopping.catalog import (
    parse_listing,
    resolve_category,
    search_sorted,
    search_url,
)
from lk47.skills.shopping.cart import _head_noun
from lk47.skills.shopping.orders import (
    _mentions,
    _past_span,
    discounted_spend,
    fulfilled_orders,
    latest_order_number,
    latest_order_total,
    order_info,
    parse_history,
    parse_order_view,
    refund,
    spend,
)
from lk47.skills.shopping.product import parse_product, parse_reviews
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/shopping"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


@pytest.fixture(autouse=True)
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SHOPPING", "http://shop.invalid")


def finish(skill: Generator[Act, PageSnapshot, str], pages: list[str]) -> str:
    next(skill)
    for page in pages[:-1]:
        skill.send(snapshot(page))
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot(pages[-1]))
    return str(done.value.value)


def test_order_history_rows() -> None:
    rows = parse_history(snapshot("order_history.html"))
    assert len(rows) == 37
    assert rows[0].number == "000000170" and rows[0].status == "Canceled" and rows[0].order_id == 170
    assert rows[0].total == Decimal("365.42") and str(rows[0].placed) == "2023-05-17"
    assert str(min(r.placed for r in rows)) == "2022-03-02"


def test_order_view_items_totals_and_boxes() -> None:
    detail = parse_order_view(snapshot("order_view_180.html"))
    assert detail.number == "000000180" and detail.status == "Complete"
    assert detail.placed == "March 11, 2023"
    assert detail.items[0].sku == "B087QJN9W1" and detail.items[0].options == {"Color": "Black"}
    assert detail.totals["Grand Total"] == Decimal("65.32")
    assert detail.totals["Shipping & Handling"] == Decimal("25.00")
    assert detail.boxes["Shipping Method"] == "Flat Rate - Fixed"
    assert "101 S San Mateo Dr" in detail.boxes["Billing Address"]


@pytest.mark.parametrize(
    ("status", "total", "number"),
    [
        ("cancelled", "$365.42", "000000170"),
        ("pending", "$754.99", "000000189"),
        ("complete", "$65.32", "000000180"),
        ("non-cancelled", "$754.99", "000000189"),
        ("processing", "N/A", "N/A"),
        ("on hold", "N/A", "N/A"),
    ],
)
def test_latest_order_by_status(status: str, total: str, number: str) -> None:
    assert finish(latest_order_total(status), ["order_history.html"]) == total
    assert finish(latest_order_number(status), ["order_history.html"]) == number


def test_order_statuses_for_two_numbers() -> None:
    assert finish(order_info("order statuses", "170 and 189"), ["order_history.html"]) == (
        "170: canceled; 189: pending"
    )


def test_fulfilled_orders_count_complete_orders_in_the_window() -> None:
    assert finish(fulfilled_orders("over the past four month", "6/12/2023"), ["order_history.html"]) == (
        "3 orders, $845.49 total spend"
    )
    assert finish(fulfilled_orders("over the past year", "6/12/2023"), ["order_history.html"]) == (
        "21 orders, $6560.69 total spend"
    )
    assert str(_past_span(__import__("datetime").date(2023, 6, 12), "over the past three days")) == "2023-06-09"


def test_spend_excludes_cancelled_orders() -> None:
    assert finish(spend("in July 2022"), ["order_history.html"]) == "40.16"
    assert finish(spend("on 4/19/2023"), ["order_history.html"]) == "0"
    # February holds two completed orders, 762.18 and 185.32; the task reference lists only the first
    assert finish(spend("each month from Jan to the end of March 2023"), ["order_history.html"]) == (
        "Jan: 572.88, Feb: 947.50, Mar: 83.31"
    )
    assert finish(discounted_spend("on November 2022"), ["order_history.html"]) == "359.546"


def test_refund_sums_cancelled_orders() -> None:
    assert finish(refund("April 2022"), ["order_history.html"]) == "0"
    assert finish(refund("Feb 2023"), ["order_history.html"]) == "406.53"
    assert finish(refund("2022"), ["order_history.html"]) == "3053.97"
    skill = refund("May 2023", shipping="kept")
    next(skill)
    assert isinstance(skill.send(snapshot("order_history.html")), Goto)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("order_view_170.html"))
    assert done.value.value == "350.42"


def test_search_urls() -> None:
    assert search_url("usb wifi") == "http://shop.invalid/catalogsearch/result/index/?q=usb+wifi"
    first = next(search_sorted("chairs", "ascending price"))
    assert isinstance(first, Goto)
    assert first.url.endswith("?q=chairs&product_list_order=price&product_list_dir=asc")
    first = next(search_sorted("Canon photo printer", "search relevance, from most to least"))
    assert isinstance(first, Goto) and first.url.endswith("?q=Canon+photo+printer")


@pytest.mark.parametrize(
    ("category", "path"),
    [
        ("Video Game", "/video-games.html"),
        ("Headphones", "/electronics/headphones.html"),
        ("Men shoes", "/clothing-shoes-jewelry/men/shoes.html"),
        ("Woman clothing", "/clothing-shoes-jewelry/women/clothing.html"),
        ("Cabinets, Racks & Shelves", "/office-products/office-furniture-lighting/cabinets-racks-shelves.html"),
        ("PS4 accessories", "/video-games/playstation-4/accessories.html"),
        ("nutrition bars and drinks", "/health-household/diet-sports-nutrition/nutrition-bars-drinks.html"),
        ("living room furtniture", "/home-kitchen/furniture/living-room-furniture.html"),
        ("kids' bedding", "/home-kitchen/bedding/kids-bedding.html"),
        ("makeup remover", "/beauty-personal-care/makeup/makeup-remover.html"),
    ],
)
def test_categories_resolve_from_the_menu(category: str, path: str) -> None:
    assert resolve_category(snapshot("home.html"), category).endswith(path)


def test_listing_and_product_parsing() -> None:
    items = parse_listing(snapshot("search_xbox.html"))
    assert len(items) == 36 and items[0].price == Decimal("24.96")
    rated = next(i for i in items if i.rating is not None)
    assert rated.rating == 93 and rated.reviews == 6
    product = parse_product(snapshot("product_headphones.html"))
    assert product.product_id == 76525 and product.sku == "B086GNDL8K" and product.rating == 75
    reviews = parse_reviews(snapshot("reviews_76525.html"))
    assert len(reviews) == 12 and reviews[0].author == "Jenna Kaufman" and reviews[0].rating == 100


def test_refund_message_names_order_sku_and_breakage() -> None:
    skill = refund_message("iphone case", "180", "it broke after just three days of use")
    next(skill)
    assert isinstance(skill.send(snapshot("order_history.html")), Goto)
    assert isinstance(skill.send(snapshot("order_view_180.html")), Goto)
    typed = skill.send(snapshot("contact.html"))
    assert isinstance(typed, Type)
    for needed in ("refund", "it broke after just three days of use", "180", "B087QJN9W1", "12.99"):
        assert needed in typed.text
    skill = coupon_request("they promised me a coupon last time")
    next(skill)
    typed = skill.send(snapshot("contact.html"))
    assert isinstance(typed, Type) and "coupon" in typed.text and "promised" in typed.text
    assert "fill(" in render(typed)


def test_budget_capacity_and_brand_query_parsing() -> None:
    from lk47.intents import parse
    from lk47.plan import build
    from lk47.skills.shopping.cart import _budget, _unit, capacity

    assert _budget("between 100 and 200") == ("100", "200")
    assert _budget("above 1000") == ("1000", "")
    assert _budget("under 60") == ("0", "60")
    assert _budget("above 50 but under 129.99") == ("50", "129.99")
    assert _unit("12 pairs") == (12, "pair") and _unit("1TB") == (1, "tb")
    assert capacity("Game Card Case with 24 Game Card Slots and 24 Micro SD Card Slots", "card") == 24
    assert capacity("Over the Door Shoe Organizer, 24 Large Pockets (12 Pairs)", "pair") == 12
    plan = build(parse("Provide me with the full names of chargers from Anker, and also share the price range for the available models"))
    assert plan.calls[0].literals == {"query": "Anker chargers", "brand": "Anker"}
    plan = build(parse("Please provide me with the complete product names of Oral B brush heads designed for children, along with their corresponding price range per brush"))
    assert plan.calls[0].literals == {"query": "Oral B brush heads children", "brand": "Oral"}


def test_pack_counts_and_tab_titles() -> None:
    from lk47.actions import Focus, render
    from lk47.skills.shopping.cart import pack_count
    from lk47.snapshot import tab_titles

    assert pack_count("Tall Pink Taper Candles 4 Piece, Orange Colored Tapered Candles") == 4
    assert pack_count("SPAAS White Taper Candles - 4 Pack, 10 Inch Tall") == 4
    assert pack_count("Ciclon Energy Drink Regular, 24 Cans, 8.3oz") == 24
    assert pack_count("V8 +Energy Drink 8 Ounce Can (Pack of 24)") == 24
    assert pack_count("Tazrigo 5pcs White Dental Resin Brush Pens") == 5
    assert pack_count("Vidpro MP-10 Monopod") == 1
    assert tab_titles("Tab 0 (current): First | Tab 1: Second\n[1] RootWebArea") == ("First", "Second")
    assert tab_titles("[1] RootWebArea") == ()
    assert render(Focus(2)) == "page.page_focus(2)"


def test_capacities_from_names_and_descriptions() -> None:
    from lk47.skills.shopping.cart import _capacities, capacity

    assert _capacities("HEIYING Case with 24 Game Card Slots and 24 Micro SD Card Slots", "card") == [24, 24]
    assert _capacities("Capacity: 40 units Nintendo Switch games, holds up to 40 video games", "card") == [40, 40]
    assert _capacities("Over 10 different colors for choose freely", "card") == []
    assert _capacities("Shoe Rack 32 Pair Plastic Shelves", "pair") == [32]
    assert _capacities("Over The Door Organizer with 24 Large Fabric Pockets", "pair") == [12]
    assert _capacities("External Hard Drive 2TB Ultra Thin 2000GB", "tb") == [2, 2]
    assert capacity("Game Card Holder Storage Case for Nintendo Switch Games", "card") is None


def test_spans_from_a_point_to_a_point() -> None:
    from datetime import date

    from lk47.skills.shopping.orders import _range

    span = _range("from mid Jan to the end Jan 2023")
    assert (span.start, span.end) == (date(2023, 1, 15), date(2023, 1, 31))
    span = _range("during 1/29/2023")
    assert (span.start, span.end) == (date(2023, 1, 29), date(2023, 1, 29))
    span = _range("from the beginning of March 2022 to April 2022")
    assert (span.start, span.end) == (date(2022, 3, 1), date(2022, 4, 30))


def test_container_kind_phrases() -> None:
    from lk47.skills.shopping.cart import _kind_phrase

    assert _kind_phrase("HEIYING Game Card Case for Nintendo Switch", "card")
    assert _kind_phrase("Game Card Holder Storage Case for Nintendo Switch Games", "card")
    assert _kind_phrase("Game Cartridge Holder Case for 160 Nintendo 3DS", "card")
    assert not _kind_phrase("Car Headrest Mount Holder for Nintendo Switch with 10 Game Card Slots", "card")
    assert _kind_phrase("Onlyeasy Over The Door Shoe Storage Organizer", "shoe")


def test_criticism_sentences_leave_out_praise() -> None:
    from lk47.skills.shopping.product import CRITICAL, PRAISE, _sentences

    parts = _sentences("The 39 was too small.They are so cute! I am afraid the 40 will be too big.")
    assert parts == ["The 39 was too small.", "They are so cute!", "I am afraid the 40 will be too big."]
    kept = [s for s in parts if not (PRAISE.search(s) and not CRITICAL.search(s))]
    assert " ".join(kept) == "The 39 was too small. I am afraid the 40 will be too big."


def test_head_noun_leaves_out_what_a_product_fits() -> None:
    assert _head_noun("Microsoft Xbox Controller (Carbon Black) for Series X, Series S") == (
        "controller"
    )
    assert _head_noun("Wired Controller for Xbox One, YCCSKY Xbox One Wired Gaming") == "controller"
    assert _head_noun("Altec Lansing Xbox Controller Charger Micro USB Cable") == "cable"
    assert _head_noun("SCUF Universal Controller Protection Case Light Gray for Xbox") == "gray"


def test_item_words_match_short_suffixed_forms() -> None:
    canvas = "Forest Canvas Wall Art Print Rustic Scenic Colorful Picture Artwork Framed Wall Art"
    sofa = "Tmosi Velvet Arm Loveseat Sofa, Accent Sofa Furniture with Wood Frame"
    assert _mentions(canvas, "picture frame", every=True)
    assert not _mentions(sofa, "picture frame", every=True)
    assert not _mentions("Crest Toothpaste", "toothbrush")
