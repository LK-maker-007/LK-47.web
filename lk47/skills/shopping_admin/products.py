from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from lk47.actions import Click, Goto, Hover, Locator
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import choose_option, replace_text
from lk47.skills.shopping_admin import uigrid
from lk47.snapshot import PageSnapshot

GRID = "catalog/product/"
SIMPLE = "Simple Product"
CONFIGURABLE = "Configurable Product"

COLORS = {
    "black",
    "blue",
    "brown",
    "gray",
    "green",
    "lavender",
    "multi",
    "orange",
    "purple",
    "red",
    "white",
    "yellow",
}
LETTER_SIZES = ("XS", "S", "M", "L", "XL")
SIZE_WORDS = {
    "extra small": "XS",
    "small": "S",
    "medium": "M",
    "large": "L",
    "extra large": "XL",
}
FILLERS = {
    "a",
    "all",
    "an",
    "and",
    "every",
    "for",
    "from",
    "in",
    "of",
    "option",
    "options",
    "size",
    "sizes",
    "the",
    "to",
    "variants",
    "with",
}
EVERY_SIZE = ("*",)
PRICE = "input[name='product[price]']"
QUANTITY = "input[name='product[quantity_and_stock_status][qty]']"
STOCK_STATUS = "select[name='product[quantity_and_stock_status][is_in_stock]']"


@dataclass(frozen=True)
class ProductRow:
    product_id: int
    name: str
    kind: str
    sku: str
    price: Decimal | None
    quantity: int | None
    status: str

    @property
    def variant(self) -> tuple[str, str] | None:
        # child skus end in "-<size>-<color>", for example MH05-XS-Red or MP12-33-Blue
        parts = self.sku.split("-")
        if (
            len(parts) >= 3
            and parts[-1].isalpha()
            and (parts[-2] in LETTER_SIZES or parts[-2].isdigit())
        ):
            return parts[-2], parts[-1]
        return None

    @property
    def base_name(self) -> str:
        if self.variant is None:
            return self.name
        size, color = self.variant
        return re.sub(rf"\s*-\s*{size}\s*-\s*{color}$", "", self.name)


def parse_products(snapshot: PageSnapshot) -> list[ProductRow]:
    rows = []
    for row in uigrid.grid_rows(snapshot):
        c = row.cells
        if len(c) < 12 or not c[1].isdigit():
            continue
        price = Decimal(c[7].replace("$", "").replace(",", "")) if c[7] else None
        quantity = int(Decimal(c[8])) if c[8] else None
        rows.append(ProductRow(int(c[1]), c[3], c[4], c[6], price, quantity, c[11]))
    return rows


@dataclass(frozen=True)
class Spec:
    words: tuple[str, ...]
    color: str | None
    sizes: tuple[str, ...] | None


def _size_token(word: str) -> str:
    return word.upper() if word.upper() in LETTER_SIZES else word


def _letter_sizes(bound: str, above: bool) -> tuple[str, ...]:
    index = LETTER_SIZES.index(bound.upper())
    return LETTER_SIZES[index:] if above else LETTER_SIZES[:index]


def parse_spec(phrase: str) -> Spec:
    text = f" {phrase.strip()} "
    sizes: tuple[str, ...] | None = None
    if m := re.search(r"\bsizes?\s+(\w+)\s+and\s+(?:above|up|larger)\b", text, flags=re.I):
        sizes = _letter_sizes(m.group(1), above=True)
    elif m := re.search(r"\bsizes?\s+(?:below|under|smaller than)\s+(\w+)\b", text, flags=re.I):
        sizes = _letter_sizes(m.group(1), above=False)
    elif m := re.search(r"\b(?:all|every)\s+sizes?\b", text, flags=re.I):
        sizes = EVERY_SIZE
    elif m := re.search(
        r"\b((?:extra\s+)?(?:small|medium|large)(?:\s+and\s+(?:extra\s+)?(?:small|medium|large))*)"
        r"\s+sizes?\b",
        text,
        flags=re.I,
    ):
        named = re.split(r"\s+and\s+", m.group(1).lower())
        sizes = tuple(SIZE_WORDS[" ".join(n.split())] for n in named)
    elif m := re.search(r"\bsizes?\s+(\w+)\b", text, flags=re.I):
        sizes = (_size_token(m.group(1)),)
    if m:
        text = text[: m.start()] + " " + text[m.end() :]
    color = None
    words = []
    for clean in re.findall(r"[A-Za-z0-9]+", re.sub(r"'s\b", "", text)):
        if clean.lower() in COLORS and color is None:
            color = clean.capitalize()
        elif clean.lower() not in FILLERS:
            words.append(clean)
    return Spec(tuple(words), color, sizes)


def _damerau_within_one(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
        if len(diffs) <= 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def same_word(a: str, b: str) -> bool:
    # catalog spellings differ from the intents by plural, suffix or a one-letter slip:
    # pant/pants, sweater/sweatshirt, lHelios/Helios, Aeno/Aeon, hoodie/Hoodlie
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]:
        return True
    return len(a) >= 4 and _damerau_within_one(a, b)


def _name_words(name: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", name)


def word_hits(row: ProductRow, spec: Spec) -> int:
    tokens = _name_words(row.base_name)
    return sum(any(same_word(w, t) for t in tokens) for w in spec.words)


def matches(row: ProductRow, spec: Spec) -> bool:
    tokens = _name_words(row.base_name)
    hits = [any(same_word(w, t) for t in tokens) for w in spec.words]
    proper = [h for w, h in zip(spec.words, hits, strict=True) if w[:1].isupper()]
    if not all(proper) or sum(hits) * 2 < len(hits):
        return False
    if spec.color is None and spec.sizes is None:
        return True
    variant = row.variant
    if variant is None:
        return False
    size, color = variant
    if spec.color is not None and color.lower() != spec.color.lower():
        return False
    return spec.sizes is None or spec.sizes == EVERY_SIZE or size in spec.sizes


def find_products(words: Sequence[str]) -> Skill[list[ProductRow]]:
    # the grid search is a conjunction of its words and misses on any slip ("sweater" for
    # "Sweatshirt"), so the search uses one word, proper names first, and the rows are matched here
    yield from uigrid.open_grid(GRID)
    keys = [w for w in words if w[:1].isupper()]
    keys += sorted((w for w in words if w not in keys), key=len, reverse=True)[:1]
    if not keys:
        raise Precondition("no product words to search for")
    for i, key in enumerate(keys):
        if i:
            yield Click(uigrid.header_button("Clear all"))
        snapshot = yield from uigrid.search(key)
        rows = parse_products(snapshot)
        if rows:
            return rows
    raise Precondition(f"no products found for {' '.join(words)!r}")


def catalog_product(rows: list[ProductRow], spec: Spec) -> ProductRow:
    matched = sorted((r for r in rows if matches(r, spec)), key=lambda r: -word_hits(r, spec))
    parents = [r for r in matched if r.kind == CONFIGURABLE]
    standalone = [r for r in matched if r.kind == SIMPLE and r.variant is None]
    for group in (parents, standalone, matched):
        if group:
            return group[0]
    raise Precondition(f"no product matches {' '.join(spec.words)!r}")


def children(rows: list[ProductRow], spec: Spec) -> list[ProductRow]:
    found = [r for r in rows if r.kind == SIMPLE and r.variant is not None and matches(r, spec)]
    if not found:
        raise Precondition(f"no variants match {' '.join(spec.words)!r}")
    return found


def edit_url(product_id: int) -> str:
    return f"{site_url('SHOPPING_ADMIN')}/catalog/product/edit/id/{product_id}/"


def save_product() -> Skill[PageSnapshot]:
    snapshot = yield Click(Locator.role("button", name="Save", exact=True))
    if "You saved the product" not in snapshot.html:
        # the redirect after a save can outlast the harness pause; observe once more
        snapshot = yield Hover(Locator.css("body"))
    if "You saved the product" not in snapshot.html:
        raise Postcondition(f"product not saved, landed on {snapshot.url}")
    return snapshot


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def adjust(price: Decimal, action: str, amount: str) -> Decimal:
    sign = -1 if re.match(r"(?i)(reduce|decrease|lower|cut|drop)", action.strip()) else 1
    text = amount.strip()
    delta = price * Decimal(text[:-1]) / 100 if text.endswith("%") else Decimal(text.lstrip("$"))
    return price + sign * delta


def set_price(row: ProductRow, value: Decimal) -> Skill[None]:
    yield Goto(edit_url(row.product_id))
    yield from replace_text(Locator.css(PRICE), money(value))
    yield from save_product()


def disable_product(product: str) -> Skill[str]:
    rows = yield from find_products(parse_spec(product).words)
    target = catalog_product(rows, parse_spec(product))
    yield Goto(edit_url(target.product_id))
    yield Click(Locator.css("input[name='product[status]'] + label"))
    yield from save_product()
    return ""


def out_of_stock(product: str) -> Skill[str]:
    spec = parse_spec(product)
    rows = yield from find_products(spec.words)
    target = catalog_product(rows, spec)
    yield Goto(edit_url(target.product_id))
    yield from choose_option(Locator.css(STOCK_STATUS), "Out of Stock")
    yield from save_product()
    return ""


def mark_on_sale(brand: str) -> Skill[str]:
    rows = yield from find_products([brand])
    spec = Spec((brand, "shirts"), None, None)
    targets = [r for r in rows if r.kind == CONFIGURABLE and matches(r, Spec((brand,), None, None))]
    targets = [r for r in targets if "shirt" in r.base_name.lower()] or [
        r for r in rows if r.kind == CONFIGURABLE and matches(r, spec)
    ]
    if not targets:
        raise Precondition(f"no {brand} shirts in the catalog")
    for row in targets:
        yield Goto(edit_url(row.product_id))
        yield Click(Locator.css("input[name='product[sale]'] + label"))
        yield from save_product()
    return ""


def change_price(action: str, amount: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    m = re.search(r"/catalog/product/edit/id/(\d+)/", snapshot.url)
    if m is None:
        raise Precondition(f"not on a product page: {snapshot.url}")
    product_id = m.group(1)
    yield from uigrid.open_grid(GRID)
    snapshot = yield from uigrid.apply_filters(
        {"entity_id[from]": product_id, "entity_id[to]": product_id}, {}
    )
    rows = [r for r in parse_products(snapshot) if r.product_id == int(product_id)]
    if not rows or rows[0].price is None:
        raise Postcondition(f"no priced row for product {product_id}")
    yield from set_price(rows[0], adjust(rows[0].price, action, amount))
    return ""


def change_config_price(action: str, config: str, amount: str) -> Skill[str]:
    spec = parse_spec(config)
    rows = yield from find_products(spec.words)
    for row in children(rows, spec):
        if row.price is None:
            raise Postcondition(f"no price in the grid for {row.sku}")
        yield from set_price(row, adjust(row.price, action, amount))
    return ""


def _deliveries(text: str) -> list[tuple[int, Spec]]:
    out: list[tuple[int, Spec]] = []
    for segment in re.split(r"\s+and\s+(?=\d)", text.strip()):
        m = re.match(r"(\d+)\s*(.*)", segment)
        if m is None:
            raise Precondition(f"no quantity in {segment!r}")
        spec = parse_spec(m.group(2))
        if not spec.words and out:
            spec = Spec(out[-1][1].words, spec.color, spec.sizes)
        out.append((int(m.group(1)), spec))
    return out


def restock(quantity: str, product: str = "") -> Skill[str]:
    deliveries = _deliveries(f"{quantity} {product}".strip())
    rows = yield from find_products(deliveries[0][1].words)
    for count, spec in deliveries:
        for row in children(rows, spec):
            if row.quantity is None:
                raise Postcondition(f"no quantity in the grid for {row.sku}")
            yield Goto(edit_url(row.product_id))
            yield from replace_text(Locator.css(QUANTITY), str(row.quantity + count))
            if row.quantity == 0:
                yield from choose_option(Locator.css(STOCK_STATUS), "In Stock")
            yield from save_product()
    return ""


def low_units(Attribute: str, N: str) -> Skill[str]:  # noqa: N803  slot names from the template
    low, _, high = N.partition("-")
    yield from uigrid.open_grid(GRID)
    snapshot = yield from uigrid.apply_filters(
        {"qty[from]": low.strip(), "qty[to]": (high or low).strip()}, {"Type": SIMPLE}
    )
    rows = parse_products(snapshot)
    if not rows:
        return "N/A"
    key = Attribute.lower()
    if "sku" in key:
        values = [r.sku for r in rows]
    elif "brand" in key:
        values = list(dict.fromkeys(_name_words(r.base_name)[0] for r in rows))
    elif "color" in key:
        return "; ".join(f"{r.base_name}: {r.variant[1] if r.variant else ''}" for r in rows)
    elif "size" in key:
        values = [f"{r.base_name}: {r.variant[0]}" if r.variant else r.name for r in rows]
    else:
        values = [r.name for r in rows]
    return ", ".join(values)


REGISTRY["shopping_admin.disable_product"] = disable_product
REGISTRY["shopping_admin.out_of_stock"] = out_of_stock
REGISTRY["shopping_admin.mark_on_sale"] = mark_on_sale
REGISTRY["shopping_admin.change_price"] = change_price
REGISTRY["shopping_admin.change_config_price"] = change_config_price
REGISTRY["shopping_admin.restock"] = restock
REGISTRY["shopping_admin.low_units"] = low_units
