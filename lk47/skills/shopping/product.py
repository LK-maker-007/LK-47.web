from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from lk47.actions import Click, Goto, Hover, Locator, Press, Type
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.shopping.catalog import parse_listing, search_url
from lk47.skills.shopping.orders import STOPWORDS, _find_item, history
from lk47.snapshot import PageSnapshot

# a review's rating is a percentage; three stars is 60%
LOW = 60
HIGH = 80


@dataclass(frozen=True)
class Product:
    product_id: int
    name: str
    sku: str
    price: Decimal | None
    rating: int | None
    review_count: int


@dataclass(frozen=True)
class Review:
    title: str
    rating: int
    author: str
    posted: str
    text: str


def parse_product(snapshot: PageSnapshot) -> Product:
    pid = snapshot.value("input[name='product']")
    name = snapshot.text("h1 .base")
    if pid is None or name is None:
        raise Postcondition(f"not a product page: {snapshot.url}")
    price = snapshot.css(".product-info-price .price-wrapper[data-price-amount]")
    rating = snapshot.css(".product-reviews-summary .rating-result[title]")
    count = re.search(
        r"(\d+)\s+Review", snapshot.text(".product-reviews-summary .reviews-actions") or ""
    )
    return Product(
        int(pid),
        name,
        snapshot.text(".product.attribute.sku .value") or "",
        Decimal(str(price[0].get("data-price-amount"))) if price else None,
        int(str(rating[0].get("title")).rstrip("%")) if rating else None,
        int(count.group(1)) if count else 0,
    )


def parse_reviews(snapshot: PageSnapshot) -> list[Review]:
    reviews = []
    for li in snapshot.css(".review-item"):
        rating = li.cssselect(".rating-result[title]")
        author = (
            " ".join(li.cssselect(".review-author")[0].text_content().split())
            if li.cssselect(".review-author")
            else ""
        )
        reviews.append(
            Review(
                " ".join(li.cssselect(".review-title")[0].text_content().split())
                if li.cssselect(".review-title")
                else "",
                int(str(rating[0].get("title")).rstrip("%")) if rating else 0,
                author.removeprefix("Review by").strip(),
                " ".join(li.cssselect(".review-date")[0].text_content().split())
                .removeprefix("Posted on")
                .strip()
                if li.cssselect(".review-date")
                else "",
                " ".join(li.cssselect(".review-content")[0].text_content().split())
                if li.cssselect(".review-content")
                else "",
            )
        )
    return reviews


def current_product() -> Skill[Product]:
    snapshot = yield Hover(Locator.css("body"))
    if "/product/" in snapshot.url or not snapshot.html.strip():
        snapshot = yield Goto(snapshot.url)
    return parse_product(snapshot)


def reviews_of(product_id: int) -> Skill[list[Review]]:
    # the review tab loads this listing by XHR; opened directly it is a plain page
    snapshot = yield Goto(
        f"{site_url('SHOPPING')}/review/product/listAjax/id/{product_id}/?limit=50"
    )
    return parse_reviews(snapshot)


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2]


def _mentions(review: Review, description: str) -> bool:
    words = _content_words(description)
    text = f"{review.title} {review.text}".lower()
    hits = sum(re.search(rf"\b{re.escape(w[:5])}", text) is not None for w in words)
    return bool(words) and hits * 2 >= len(words)


def reviewers_mentioning(description: str) -> Skill[str]:
    product = yield from current_product()
    reviews = yield from reviews_of(product.product_id)
    names = [r.author for r in reviews if _mentions(r, description)]
    return ", ".join(dict.fromkeys(names)) if names else "N/A"


PRAISE = re.compile(
    r"\b(?:cute|love[sd]?|great|perfect|beautiful|compliments?|nice|excellent|amazing|awesome|"
    r"happy|best|wonderful|recommend|glad|favou?rite|pleased|like it)\b",
    re.I,
)
CRITICAL = re.compile(
    r"\b(?:not|no|never|but|except|however|too|problem|disappoint\w*|return\w*|broke\w*|"
    r"cheap|wrong|poor|small|big|tight|loose|hurts?|painful)\b|n't",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s*(?=[A-Z])", text) if p.strip()]


def main_criticisms() -> Skill[str]:
    product = yield from current_product()
    reviews = yield from reviews_of(product.product_id)
    ordered = sorted(reviews, key=lambda r: r.rating)
    kept = [
        s
        for r in ordered
        for s in _sentences(r.text)
        if not (PRAISE.search(s) and not CRITICAL.search(s))
    ]
    return " ".join(kept) if kept else "N/A"


def _search_first(query: str) -> Skill[str]:
    snapshot = yield Goto(search_url(query))
    items = parse_listing(snapshot)
    if not items:
        raise Precondition(f"no products for {query!r}")
    return items[0].url


def _add_to_wishlist() -> Skill[str]:
    snapshot = yield Click(Locator.css("a.towishlist"))
    if "/wishlist/" not in snapshot.url:
        raise Postcondition(f"wish list not shown after adding, at {snapshot.url}")
    return ""


def wishlist_this() -> Skill[str]:
    return (yield from _add_to_wishlist())


def wishlist_product(product: str) -> Skill[str]:
    url = yield from _search_first(product)
    yield Goto(url)
    return (yield from _add_to_wishlist())


def product_rating(product: str) -> Skill[str]:
    url = yield from _search_first(product)
    snapshot = yield Goto(url)
    found = parse_product(snapshot)
    if found.rating is None:
        return "N/A"
    return f"{found.rating}% ({round(found.rating / 20)} stars)"


def _stars(stars: str) -> tuple[int, int]:
    numbers = [int(n) for n in re.findall(r"\d", stars)]
    return min(numbers) * 20, max(numbers) * 20


def _brand_reviews(brand: str, product_type: str) -> Skill[list[Review]]:
    snapshot = yield Goto(search_url(f"{brand} {product_type}"))
    reviews: list[Review] = []
    for item in parse_listing(snapshot):
        if brand.lower() not in item.name.lower() or item.reviews == 0:
            continue
        page = yield Goto(item.url)
        reviews += yield from reviews_of(parse_product(page).product_id)
    return reviews


def brand_reviewers(stars: str, brand: str, product_type: str) -> Skill[str]:
    low, high = _stars(stars)
    reviews = yield from _brand_reviews(brand, product_type)
    names = [r.author for r in reviews if low <= r.rating <= high]
    return ", ".join(dict.fromkeys(names)) if names else "N/A"


TOPIC_WORDS = {
    "quality": (
        "broke",
        "broken",
        "peel",
        "scratch",
        "chip",
        "crack",
        "flimsy",
        "cheap",
        "quality",
    ),
    "looking": ("cute", "pretty", "beautiful", "gorgeous", "chic", "classy", "stylish", "stunning"),
}


def brand_reviewers_saying(topic: str, brand: str, product_type: str) -> Skill[str]:
    reviews = yield from _brand_reviews(brand, product_type)
    words = TOPIC_WORDS[topic]
    names = [r.author for r in reviews if any(w in f"{r.title} {r.text}".lower() for w in words)]
    return ", ".join(dict.fromkeys(names)) if names else "N/A"


def rate_purchase(product: str, num_star: str, nickname: str) -> Skill[str]:
    rows = yield from history()
    found = yield from _find_item(rows, product, lambda r: True)
    if found is None:
        raise Precondition(f"no purchase of {product!r}")
    snapshot = yield Goto(search_url(found[2].sku))
    items = parse_listing(snapshot)
    if not items:
        raise Postcondition(f"sku {found[2].sku} not in the catalog search")
    yield Goto(items[0].url)
    yield Click(Locator.css("#tab-label-reviews-title"))
    # the star labels overlap, so only the one-star label takes a click; the arrow keys move
    # the choice along the group, alternating keys so no three presses are identical
    yield Click(Locator.css("#review-form label[for='Rating_1']"))
    for step in range(int(num_star) - 1):
        yield Press("ArrowRight" if step % 2 == 0 else "ArrowDown")
    yield Type(Locator.css("#review-form input[name='nickname']"), nickname)
    yield Type(Locator.css("#review-form input[name='title']"), f"{num_star} stars")
    yield Type(
        Locator.css("#review-form textarea[name='detail']"),
        f"Rated {num_star} stars for my recent purchase.",
    )
    snapshot = yield Click(Locator.css("#review-form button.submit"))
    if "You submitted your review" not in snapshot.html:
        raise Postcondition("no confirmation after submitting the review")
    return ""


REGISTRY["shopping.reviewers_mentioning"] = reviewers_mentioning
REGISTRY["shopping.main_criticisms"] = main_criticisms
REGISTRY["shopping.wishlist_this"] = wishlist_this
REGISTRY["shopping.wishlist_product"] = wishlist_product
REGISTRY["shopping.product_rating"] = product_rating
REGISTRY["shopping.brand_reviewers"] = brand_reviewers
REGISTRY["shopping.brand_reviewers_saying"] = brand_reviewers_saying
REGISTRY["shopping.rate_purchase"] = rate_purchase
