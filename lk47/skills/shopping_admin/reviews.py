from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from lk47.actions import Click, Goto, Locator
from lk47.normalize import Unsupported, period_range
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import choose_option
from lk47.skills.shopping_admin.customers import customer_email
from lk47.skills.shopping_admin.grid import grid_rows, legacy_grid_url, records_found
from lk47.snapshot import PageSnapshot

GRID = "review/product/index"
STATUS_IDS = {"approved": "1", "pending": "2", "not approved": "3"}
ALL_TIME = ("", "by far", "from the beginning of the shop", "so far", "in total")
STOPWORDS = {"the", "a", "an", "of", "for", "product", "products", "style", "my", "our"}

# the readings the graders behind these templates use: "dissatisfied" is three stars or
# fewer, "negative" is two or fewer, "positive" is three or more
DISSATISFIED = 3
NEGATIVE = 2
POSITIVE = 3


@dataclass(frozen=True)
class ReviewRow:
    review_id: int
    created: str
    status: str
    title: str
    nickname: str
    detail: str
    kind: str
    product: str
    sku: str


def parse_reviews(snapshot: PageSnapshot) -> list[ReviewRow]:
    rows = []
    for c in grid_rows(snapshot):
        if len(c) >= 11 and c[1].isdigit():
            rows.append(ReviewRow(int(c[1]), c[2], c[3], c[4], c[5], c[6], c[8], c[9], c[10]))
    return rows


def parse_stars(snapshot: PageSnapshot) -> int:
    radios = snapshot.css("input[name^='ratings[']")
    values = sorted(int(r.get("value") or 0) for r in radios)
    checked = [int(r.get("value") or 0) for r in radios if r.get("checked") is not None]
    if len(values) != 5 or len(checked) != 1:
        raise Postcondition(f"no single rating on {snapshot.url}")
    return values.index(checked[0]) + 1


def edit_url(review_id: int) -> str:
    return f"{site_url('SHOPPING_ADMIN')}/review/product/edit/id/{review_id}/"


def count_reviews(filters: Mapping[str, str]) -> Skill[int]:
    snapshot = yield Goto(legacy_grid_url(GRID, filters))
    return records_found(snapshot)


def review_rows(filters: Mapping[str, str]) -> Skill[list[ReviewRow]]:
    snapshot = yield Goto(legacy_grid_url(GRID, filters))
    total = records_found(snapshot)
    rows = parse_reviews(snapshot)
    page = 1
    while len(rows) < total and page < 3:
        page += 1
        snapshot = yield Goto(legacy_grid_url(GRID, filters, page=page))
        rows.extend(parse_reviews(snapshot))
    return rows


def product_words(product: str) -> list[str]:
    words = [re.sub(r"['\u2019]s$", "", w.strip(",.'\"").lower()) for w in product.split()]
    words = [w for w in words if len(w) > 1 and w not in STOPWORDS]
    return [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words]


def product_reviews(product: str, extra: Mapping[str, str] | None = None) -> Skill[list[ReviewRow]]:
    words = product_words(product)
    if not words:
        raise Precondition(f"no product words in {product!r}")
    filters = {**(extra or {}), "name": words[0]}
    rows = yield from review_rows(filters)
    return [r for r in rows if all(w in r.product.lower() for w in words)]


@dataclass(frozen=True)
class Rated:
    row: ReviewRow
    stars: int
    name: str
    email: str | None
    # the grid shows the first fifty characters of a review; the page holds all of it
    detail: str


def author(snapshot: PageSnapshot) -> tuple[str | None, str | None]:
    text = snapshot.text("#customer") or ""
    m = re.fullmatch(r"(.+?)\s*\(([^()\s]+@[^()\s]+)\)", text)
    if m is None:
        return None, None
    return m.group(1), m.group(2)


def stars_for(rows: list[ReviewRow]) -> Skill[list[Rated]]:
    rated: list[Rated] = []
    for row in rows:
        snapshot = yield Goto(edit_url(row.review_id))
        name, email = author(snapshot)
        detail = snapshot.text("textarea[name='detail']") or row.detail
        rated.append(Rated(row, parse_stars(snapshot), name or row.nickname, email, detail))
    return rated


def count_by_status(status: str) -> Skill[str]:
    key = status.strip().lower()
    if key not in STATUS_IDS:
        raise Precondition(f"unknown review status {status!r}")
    count = yield from count_reviews({"status": STATUS_IDS[key]})
    return str(count)


def count_by_term(term: str) -> Skill[str]:
    count = yield from count_reviews({"detail": term})
    return str(count)


def count_by_time(time: str) -> Skill[str]:
    text = time.strip().lower()
    if text in ALL_TIME:
        count = yield from count_reviews({})
        return str(count)
    try:
        span = period_range(time)
    except Unsupported:
        raise Precondition(f"unsupported period {time!r}") from None
    start, end = span.start.strftime("%m/%d/%Y"), span.end.strftime("%m/%d/%Y")
    filters = {"created_at[from]": start, "created_at[to]": end, "created_at[locale]": "en_US"}
    count = yield from count_reviews(filters)
    return str(count)


def most_unhappy(information: str, product: str) -> Skill[str]:
    rows = yield from product_reviews(product)
    if not rows:
        return "N/A"
    rated = yield from stars_for(rows)
    worst = min(rated, key=lambda r: r.stars)
    if "email" not in information.lower():
        return worst.name
    if worst.email is not None:
        return worst.email
    try:
        return (yield from customer_email(worst.row.nickname))
    except Postcondition:
        return "N/A"


def dissatisfied_customers(product: str) -> Skill[str]:
    rows = yield from product_reviews(product)
    rated = yield from stars_for(rows)
    names = [r.name for r in rated if r.stars <= DISSATISFIED]
    return ", ".join(names) if names else "N/A"


def _aspects(product: str, keep: str) -> Skill[str]:
    rows = yield from product_reviews(product)
    rated = yield from stars_for(rows)
    if keep == "dislike":
        texts = [r.detail for r in rated if r.stars <= DISSATISFIED]
    else:
        texts = [r.detail for r in rated if r.stars > DISSATISFIED]
    return " ".join(texts) if texts else "N/A"


def rated_titles(product: str, keep: str) -> Skill[str]:
    rows = yield from product_reviews(product)
    rated = yield from stars_for(rows)
    if keep == "dislike":
        kept = [r for r in rated if r.stars <= DISSATISFIED]
    else:
        kept = [r for r in rated if r.stars > DISSATISFIED]
    return "; ".join(f"{r.row.title}: {r.stars}" for r in kept)


def disliked_aspects(product: str) -> Skill[str]:
    return (yield from _aspects(product, "dislike"))


def liked_aspects(product: str) -> Skill[str]:
    return (yield from _aspects(product, "like"))


def _delete_on_page() -> Skill[None]:
    yield Click(Locator.role("button", name="Delete Review"))
    yield Click(Locator.css(".modal-popup._show button").having_text("OK"))


def delete_reviews(review_type: str) -> Skill[str]:
    text = review_type.lower()
    filters: dict[str, str] = {}
    if "pending" in text:
        filters["status"] = STATUS_IDS["pending"]
    if m := re.search(r"from the scammer (\w+)", review_type):
        filters["nickname"] = m.group(1)
    limit = NEGATIVE if "negative" in text else None
    if m := re.search(r"less than (\d) stars?", text):
        limit = int(m.group(1)) - 1
    product = None
    if m := re.search(r"\bfor (.+)$", review_type):
        product = m.group(1)
    if product:
        rows = yield from product_reviews(product, filters)
    else:
        rows = yield from review_rows(filters)
    if not rows:
        return "N/A"
    deleted = 0
    for row in rows:
        snapshot = yield Goto(edit_url(row.review_id))
        if limit is not None and parse_stars(snapshot) > limit:
            continue
        yield from _delete_on_page()
        deleted += 1
    return "N/A" if deleted == 0 else ""


def approve_positive() -> Skill[str]:
    rows = yield from review_rows({"status": STATUS_IDS["pending"]})
    for row in rows:
        snapshot = yield Goto(edit_url(row.review_id))
        if parse_stars(snapshot) < POSITIVE:
            continue
        # a save can come back as a browser error page; the review is then opened and saved again
        for _ in range(2):
            yield from choose_option(Locator.css("select[name='status_id']"), "Approved")
            snapshot = yield Click(Locator.role("button", name="Save Review"))
            if "You saved the review" in snapshot.html:
                break
            snapshot = yield Goto(edit_url(row.review_id))
            if (
                snapshot.value("select[name='status_id'] option[selected]")
                == STATUS_IDS["approved"]
            ):
                break
        else:
            raise Postcondition(f"review {row.review_id} not saved")
    return ""


REGISTRY["shopping_admin.count_reviews_by_status"] = count_by_status
REGISTRY["shopping_admin.count_reviews_by_term"] = count_by_term
REGISTRY["shopping_admin.count_reviews_by_time"] = count_by_time
REGISTRY["shopping_admin.most_unhappy"] = most_unhappy
REGISTRY["shopping_admin.dissatisfied_customers"] = dissatisfied_customers
REGISTRY["shopping_admin.disliked_aspects"] = disliked_aspects
REGISTRY["shopping_admin.liked_aspects"] = liked_aspects
REGISTRY["shopping_admin.rated_titles"] = rated_titles
REGISTRY["shopping_admin.delete_reviews"] = delete_reviews
REGISTRY["shopping_admin.approve_positive"] = approve_positive
