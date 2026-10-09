from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from decimal import Decimal

import lxml.html
from lxml.html import HtmlElement

from lk47.actions import Click, Focus, Goto, Hover, Locator
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.shopping.catalog import (
    Listing,
    _category,
    listing_total,
    parse_listing,
    search_url,
)
from lk47.skills.shopping.orders import (
    _find_item,
    _range,
    _within,
    amount,
    history,
    open_order,
    view_url,
)
from lk47.skills.shopping.product import parse_product, reviews_of
from lk47.skills.shopping_admin.products import same_word
from lk47.snapshot import PageSnapshot

PAGES = 4
SUCCESS = "/checkout/onepage/success/"


def checkout() -> Skill[str]:
    # the account has a default address and one shipping and one payment method, both preselected
    yield Goto(f"{site_url('SHOPPING')}/checkout/")
    yield Click(Locator.css("#shipping-method-buttons-container button.continue"))
    snapshot = yield Click(Locator.css("button.action.primary.checkout"))
    if SUCCESS not in snapshot.url:
        snapshot = yield Hover(Locator.css("body"))
    if SUCCESS not in snapshot.url:
        raise Postcondition(f"order not placed, at {snapshot.url}")
    return ""


def buy(url: str) -> Skill[str]:
    page = yield Goto(url)
    for field in page.css("#product-options-wrapper .field.required .options-list"):
        radios = field.cssselect("input[type='radio']")
        if radios and radios[0].get("id"):
            yield Click(Locator.css(f"label[for='{radios[0].get('id')}']"))
    snapshot = yield Click(Locator.css("#product-addtocart-button"))
    if "You added" not in (snapshot.text(".message-success") or ""):
        snapshot = yield Hover(Locator.css("body"))
    if "You added" not in (snapshot.text(".message-success") or ""):
        raise Postcondition(f"product not added to the cart from {url}")
    return (yield from checkout())


def reorder(product: str, time: str) -> Skill[str]:
    rows = yield from history()
    span = _range(time)
    found = yield from _find_item(
        rows, product, lambda r: r.status == "Canceled" and span.start <= r.placed <= span.end
    )
    if found is None:
        raise Precondition(f"no cancelled order with {product!r} {time}")
    yield Goto(view_url(found[0].order_id))
    snapshot = yield Click(Locator.css("a.action.order"))
    if "/checkout/cart/" not in snapshot.url:
        raise Postcondition(f"reorder did not fill the cart, at {snapshot.url}")
    return (yield from checkout())


def _budget(dollar_value: str) -> tuple[str, str]:
    numbers = re.findall(r"\d+(?:\.\d+)?", dollar_value)
    text = dollar_value.lower()
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if "under" in text or "below" in text or "less" in text:
        return "0", numbers[0]
    return numbers[0], ""


def _scan(url: str, pages: int) -> Skill[list[Listing]]:
    # the listing cannot be sorted by rating; up to `pages` pages of 36 are read
    snapshot = yield Goto(f"{url}&product_list_limit=36")
    items = parse_listing(snapshot)
    total = listing_total(snapshot)
    page = 1
    while len(items) < total and page < pages:
        page += 1
        snapshot = yield Goto(f"{url}&product_list_limit=36&p={page}")
        items += parse_listing(snapshot)
    return items


def _listing_url(category: str) -> Skill[tuple[str, list[str]]]:
    try:
        url = yield from _category(category)
    except Precondition:
        words = [w for w in re.findall(r"[a-z0-9]+", category.lower()) if len(w) >= 3]
        return search_url(category), words
    return f"{url}?", []


def _named(items: list[Listing], words: list[str]) -> list[Listing]:
    named = [i for i in items if _named_with(i, words)]
    return named or items


def buy_best_rated(product_category: str, dollar_value: str) -> Skill[str]:
    low, high = _budget(dollar_value)
    base, words = yield from _listing_url(product_category)
    joiner = "" if base.endswith("?") else "&"
    url = f"{base}{joiner}price={low}-{high}"
    if not words:
        # the store cannot sort by rating; a menu category holding more products in the budget
        # than the pages read cannot be ranked, and the purchase is reported as not possible
        first = yield Goto(f"{url}&product_list_limit=36")
        if listing_total(first) > PAGES * 36:
            return "N/A"
    items = _named((yield from _scan(url, PAGES)), words)
    rated = [i for i in items if i.rating is not None]
    if not rated:
        raise Precondition(f"no rated products in {product_category!r} for {dollar_value!r}")
    best = max(rated, key=lambda i: (i.rating or 0, -(i.price or Decimal(0))))
    return (yield from buy(best.url))


def buy_best_reviewed(category: str) -> Skill[str]:
    base, words = yield from _listing_url(category)
    joiner = "" if base.endswith("?") else "&"
    snapshot = yield Goto(
        f"{base}{joiner}product_list_order=price&product_list_dir=asc&product_list_limit=36"
    )
    items = _named(parse_listing(snapshot), words)
    reviewed = [i for i in items if i.reviews >= 5 and i.rating is not None]
    if not reviewed:
        raise Precondition(f"no product in {category!r} has five reviews")
    top = max(i.rating or 0 for i in reviewed)
    best = min(
        (i for i in reviewed if i.rating == top), key=lambda i: i.price or Decimal("Infinity")
    )
    return (yield from buy(best.url))


CONTAINER_WORDS = {
    "storage",
    "case",
    "holder",
    "option",
    "organizer",
    "a",
    "an",
    "the",
    "of",
    "for",
}
CONTAINER_KINDS = ("case", "holder", "storage", "organizer", "rack", "box", "bag", "pouch")


def _kind_phrase(name: str, noun: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    stems = (noun[:4], "cart") if noun.startswith("card") else (noun[:4],)
    return any(
        t.startswith(stems) and i + 1 < len(tokens) and tokens[i + 1].startswith(CONTAINER_KINDS)
        for i, t in enumerate(tokens)
    )


def _capacities(text: str, unit: str) -> list[int]:
    t = text.lower()
    if unit in ("tb", "gb"):
        sizes = [
            int(m.group(1)) * (1000 if m.group(2) == "tb" else 1)
            for m in re.finditer(r"(\d+)\s*(tb|gb)\b", t)
        ]
        return [n // 1000 if unit == "tb" else n for n in sizes]
    if unit == "pair":
        pairs = [int(m.group(1)) for m in re.finditer(r"(\d+)[\s-]*pairs?\b", t)]
        pockets = re.finditer(r"(\d+)\s+(?:large\s+)?(?:fabric\s+|mesh\s+)?pockets?\b", t)
        return pairs + [int(m.group(1)) // 2 for m in pockets]
    pattern = (
        rf"(\d+)\s+(?:units?\s+)?(?:nintendo\s+switch\s+)?(?:game\s+|video\s+|micro\s+sd\s+|sd\s+)?"
        rf"(?:{unit}s?|games?|slots?|cartridges?)\b"
    )
    return [int(m.group(1)) for m in re.finditer(pattern, t)]


def capacity(name: str, unit: str) -> int | None:
    found = _capacities(name, unit)
    return found[0] if found else None


def _page_capacity(snapshot: PageSnapshot, unit: str) -> int | None:
    html = re.sub(r"<style.*?</style>", "", snapshot.html, flags=re.S)
    tree: HtmlElement = lxml.html.fromstring(html)
    parts = tree.cssselect(".product.attribute.description, .product.attribute.overview")
    found = _capacities(" ".join(e.text_content() for e in parts), unit)
    return Counter(found).most_common(1)[0][0] if found else None


def _unit(min_storage: str) -> tuple[int, str]:
    m = re.match(r"\s*(\d+)\s*([A-Za-z]+)", min_storage)
    if m is None:
        raise Precondition(f"no capacity in {min_storage!r}")
    unit = m.group(2).lower().rstrip("s")
    return int(m.group(1)), unit


def _storage_candidates(product: str, unit: str, visits: int) -> Skill[list[tuple[Listing, int]]]:
    all_words = re.findall(r"[a-z0-9]+", product.lower())
    words = [w for w in all_words if w not in CONTAINER_WORDS]
    noun = words[-1] if words and any(w in CONTAINER_KINDS for w in all_words) else ""
    items: list[Listing] = []
    for page in range(1, 4):
        snapshot = yield Goto(search_url(product, product_list_limit="36", p=str(page)))
        found = parse_listing(snapshot)
        items += [
            i
            for i in found
            if i.price is not None
            and _named_with(i, words)
            and (not noun or _kind_phrase(i.name, noun))
        ]
        if len(found) < 36:
            break
    known = [(i, capacity(i.name, unit)) for i in items]
    out = [(i, c) for i, c in known if c is not None]
    unknown = sorted((i for i, c in known if c is None), key=lambda i: i.price or Decimal(0))
    for item in unknown[:visits]:
        snapshot = yield Goto(item.url)
        c = _page_capacity(snapshot, unit)
        if c is not None:
            out.append((item, c))
    return out


def cheapest_with_capacity(product: str, min_storage: str) -> Skill[str]:
    needed, unit = _unit(min_storage)
    found = yield from _storage_candidates(product, unit, visits=4)
    fitting = [(i, c) for i, c in found if c >= needed]
    if not fitting:
        raise Precondition(f"no {product!r} holds {min_storage}")
    best = min(fitting, key=lambda ic: ic[0].price or Decimal(0))
    yield Goto(best[0].url)
    return ""


def storage_for_cards(num: str) -> Skill[str]:
    needed = int(num)
    found = yield from _storage_candidates("nintendo switch game card case storage", "card", 4)
    fitting = [(i, c) for i, c in found if c >= needed]
    if not fitting:
        raise Precondition(f"no switch game card case holds {num} cards")
    best = min(fitting, key=lambda ic: (ic[1], ic[0].price or Decimal(0)))
    yield Goto(best[0].url)
    return ""


def _named_with(item: Listing, words: list[str]) -> bool:
    tokens = re.findall(r"[a-z0-9]+", item.name.lower())
    return all(any(t.startswith(w[:4]) for t in tokens) for w in words)


PRODUCT_SYNONYMS = {"bluetooth": ("wireless",), "children": ("kid",), "kids": ("child",)}
# a name's own product ends where it starts naming what it fits or comes with: "AC Adapter for
# Sony Walkman", "Toothbrush Featuring Frozen, includes 2 Brush Heads"
ACCESSORY_BOUNDARY = re.compile(r"\b(?:for|with|featuring|includes?|compatible|fits?)\b", re.I)


def _own_part(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", ACCESSORY_BOUNDARY.split(name, maxsplit=1)[0].lower())


def _has_word(tokens: list[str], word: str) -> bool:
    stems = (word[:4], *(w[:4] for w in PRODUCT_SYNONYMS.get(word, ())))
    return any(t.startswith(stems) for t in tokens)


def brand_products(query: str, brand: str) -> Skill[str]:
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", query.lower())
        if w != brand.lower() and len(w) > 1 and w != "designed"
    ]
    found: list[Listing] = []
    for page in range(1, 4):
        snapshot = yield Goto(search_url(query, product_list_limit="36", p=str(page)))
        listed = parse_listing(snapshot)
        found += [i for i in listed if i.price and brand.lower() in _own_part(i.name)]
        if len(listed) < 36:
            break
    items = [i for i in found if all(_has_word(_own_part(i.name), w) for w in words)]
    if not items:
        items = [i for i in found if any(_has_word(_own_part(i.name), w) for w in words)]
    if not items:
        return "N/A"
    prices = [i.price for i in items if i.price is not None]
    names = "; ".join(i.name for i in items)
    return f"{names}. Price range: ${min(prices):.2f} to ${max(prices):.2f}"


def pack_count(name: str) -> int:
    text = name.lower()
    if m := re.search(r"\b(?:pack|set|box|case) of (\d+)", text):
        return int(m.group(1))
    if m := re.search(
        r"\b(\d+)\s*-?\s*(?:pack|pcs|pc|pieces?|pairs?|count|cans?|bottles?|bars?|bags?|rolls?)\b",
        text,
    ):
        return int(m.group(1))
    return 1


def cheapest_unit_to_cart() -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    count = len(snapshot.tabs)
    if count == 0:
        raise Precondition("no tabs in the observation")
    best: tuple[Decimal, int] | None = None
    for tab in range(count):
        snapshot = yield Focus(tab)
        product = parse_product(snapshot)
        if product.price is None:
            continue
        unit = product.price / pack_count(product.name)
        if best is None or unit < best[0]:
            best = (unit, tab)
    if best is None:
        raise Postcondition("no priced product among the tabs")
    yield Focus(best[1])
    snapshot = yield Click(Locator.css("#product-addtocart-button"))
    yield Goto(f"{site_url('SHOPPING')}/checkout/cart/")
    return ""


def remedy_search(problem: str) -> Skill[str]:
    yield Goto(search_url(problem))
    return ""


def customer_service_number() -> Skill[str]:
    snapshot = yield Goto(f"{site_url('SHOPPING')}/contact/")
    text = " ".join((snapshot.text("#maincontent") or "").split())
    m = re.search(r"\+?\d[\d\s().-]{8,}\d", text)
    return m.group(0) if m else "N/A"


def discounted_items() -> Skill[str]:
    snapshot = yield Goto(f"{site_url('SHOPPING')}/")
    names = [
        " ".join(li.cssselect(".product-item-link")[0].text_content().split())
        for li in snapshot.css("li.product-item")
        if li.cssselect(".special-price") and li.cssselect(".product-item-link")
    ]
    return ", ".join(names) if names else "N/A"


CATEGORY_IDS = {"beauty & personal care": 3, "home & kitchen": 6, "grocery & gourmet food": 14}
CATEGORY_WORDS = {
    "food": "grocery & gourmet food",
    "cooking": "grocery & gourmet food",
    "grocery": "grocery & gourmet food",
    "hair": "beauty & personal care",
    "beauty": "beauty & personal care",
    "home": "home & kitchen",
    "decoration": "home & kitchen",
    "kitchen": "home & kitchen",
}
SHIPPING_PER_ITEM = Decimal("5.00")


def category_spend(category: str, time: str, shipping: str = "") -> Skill[str]:
    # the spend on a kind of shopping: each item of the store category in an order of the period
    # that was not cancelled, at its price plus the flat $5 shipping an item carries, unless the
    # wording leaves shipping out
    names = [
        CATEGORY_WORDS[w] for w in re.findall(r"[a-z]+", category.lower()) if w in CATEGORY_WORDS
    ]
    if not names:
        raise Precondition(f"no store category for {category!r}")
    cat = str(CATEGORY_IDS[names[0]])
    span = _range(time)
    rows = yield from history()
    total = Decimal(0)
    for row in _within(rows, span):
        if row.status == "Canceled":
            continue
        detail = yield from open_order(row.order_id)
        for item in detail.items:
            snapshot = yield Goto(search_url(item.sku, cat=cat))
            if parse_listing(snapshot):
                carried = Decimal(0) if shipping == "exclude" else SHIPPING_PER_ITEM
                total += (item.price + carried) * item.quantity
    return amount(total)


FIRST_AVAILABLE = re.compile(r"Date First Available\s*:?\s*([A-Z][a-z]+ \d{1,2},? \d{4})")
NAME_HEAD_END = re.compile(r",|\s-\s|\(|\|")


def _head_noun(name: str) -> str:
    own = ACCESSORY_BOUNDARY.split(name, maxsplit=1)[0]
    words = re.findall(r"[a-z0-9]+", NAME_HEAD_END.split(own, maxsplit=1)[0].lower())
    return words[-1] if words else ""


def released_between(product: str, first: str, last: str) -> Skill[str]:
    words = re.findall(r"[a-z0-9]+", product.lower())
    snapshot = yield Goto(search_url(product))
    items = [
        i
        for i in parse_listing(snapshot)
        if same_word(_head_noun(i.name), words[-1]) and _named_with(i, words)
    ]
    dated = []
    here = snapshot.url
    for item in items[:6]:
        page = yield Goto(item.url)
        here = page.url
        text = " ".join((page.text(".product.attribute.description") or "").split())
        if m := FIRST_AVAILABLE.search(text):
            day = datetime.strptime(m.group(1).replace(",", ""), "%B %d %Y").date()
            if int(first) <= day.year <= int(last):
                dated.append((day, item.url))
    if not dated:
        raise Precondition(f"no {product!r} first available in {first}-{last}")
    latest = max(dated)[1]
    if latest != here:
        yield Goto(latest)
    return ""


def review_titles(product: str, rating: str) -> Skill[list[str]]:
    m = re.search(r"(\d)\s*stars?", rating)
    if m is None:
        raise Precondition(f"no star count in {rating!r}")
    stars = int(m.group(1))
    snapshot = yield Goto(search_url(product))
    items = parse_listing(snapshot)
    if not items:
        raise Precondition(f"no product found for {product!r}")
    page = yield Goto(items[0].url)
    reviews = yield from reviews_of(parse_product(page).product_id)
    return [r.title for r in reviews if r.rating <= 20 * stars]


def review_summary(product_type: str, manufature: str = "") -> Skill[str]:
    name = f"{manufature} {product_type}".strip()
    snapshot = yield Goto(search_url(name))
    words = re.findall(r"[a-z0-9]+", name.lower())
    items = [i for i in parse_listing(snapshot) if _named_with(i, words) and i.reviews > 0]
    if not items:
        return "N/A"
    page = yield Goto(items[0].url)
    reviews = yield from reviews_of(parse_product(page).product_id)
    return " ".join(f"{r.author} ({r.rating}%): {r.text}" for r in reviews) if reviews else "N/A"


REGISTRY["shopping.reorder"] = reorder
REGISTRY["shopping.buy_best_rated"] = buy_best_rated
REGISTRY["shopping.buy_best_reviewed"] = buy_best_reviewed
REGISTRY["shopping.cheapest_with_capacity"] = cheapest_with_capacity
REGISTRY["shopping.storage_for_cards"] = storage_for_cards
REGISTRY["shopping.brand_products"] = brand_products
REGISTRY["shopping.cheapest_unit_to_cart"] = cheapest_unit_to_cart
REGISTRY["shopping.remedy_search"] = remedy_search
REGISTRY["shopping.customer_service_number"] = customer_service_number
REGISTRY["shopping.discounted_items"] = discounted_items
REGISTRY["shopping.review_summary"] = review_summary
REGISTRY["shopping.review_titles"] = review_titles
REGISTRY["shopping.released_between"] = released_between
REGISTRY["shopping.category_spend"] = category_spend
