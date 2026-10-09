from __future__ import annotations

import re
from dataclasses import dataclass

from lk47.actions import Click, Goto, Hover, Locator, Type
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import choose_option, replace_text
from lk47.skills.shopping_admin.products import (
    COLORS,
    catalog_product,
    edit_url,
    find_products,
    parse_spec,
    save_product,
)
from lk47.skills.shopping_admin.reviews import POSITIVE, product_reviews, stars_for
from lk47.snapshot import PageSnapshot

PRODUCT_KINDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("watch",), "Gear", "Watches"),
    (("mat", "ball", "strap", "band", "bottle", "equipment", "kit"), "Gear", "Fitness Equipment"),
    (("bag", "duffle", "backpack", "tote"), "Bag", "Bags"),
    (
        (
            "pant",
            "pants",
            "jean",
            "jeans",
            "short",
            "shorts",
            "legging",
            "leggings",
            "capri",
            "tight",
            "tights",
        ),
        "Bottom",
        "Bottoms",
    ),
    (
        (
            "shirt",
            "tee",
            "t-shirt",
            "tank",
            "top",
            "hoodie",
            "sweatshirt",
            "jacket",
            "pullover",
            "sweater",
            "bra",
        ),
        "Top",
        "Tops",
    ),
)


def classify_product(name: str) -> tuple[str, str, str | None]:
    words = [w.lower().strip(",.") for w in name.split()]
    gender = "Women" if any(w in ("women", "woman", "womens", "women's") for w in words) else None
    if gender is None and any(w in ("men", "man", "mens", "men's") for w in words):
        gender = "Men"
    for nouns, attribute_set, category in PRODUCT_KINDS:
        if any(w in nouns for w in words):
            return attribute_set, category, gender
    raise Precondition(f"no attribute set for product {name!r}")


def new_simple_product(product: str, stock: str, size: str, color: str, price: str) -> Skill[str]:
    attribute_set, category, gender = classify_product(product)
    yield Goto(f"{site_url('SHOPPING_ADMIN')}/catalog/product/new/set/4/type/simple/")
    # the Default set has no size or color; switching the set reloads the form in place
    yield Click(Locator.css("[data-role='selected-option']"))
    sets = Locator.css("[data-index='attribute_set_id'] .admin__action-multiselect-menu-inner-item")
    yield Click(sets.having_text(attribute_set))
    yield Type(Locator.css("input[name='product[name]']"), product)
    yield Type(Locator.css("input[name='product[price]']"), price.lstrip("$"))
    yield Type(Locator.css("input[name='product[quantity_and_stock_status][qty]']"), stock)
    if attribute_set in ("Top", "Bottom"):
        yield from choose_option(Locator.css("select[name='product[size]']"), size)
    yield from choose_option(Locator.css("select[name='product[color]']"), color)
    widget = "[data-index='category_ids']"
    yield Click(Locator.css(f"{widget} .admin__action-multiselect"))
    yield Type(Locator.css(f"{widget} input[data-role='advanced-select-text']"), category)
    items = Locator.css(f"{widget} .admin__action-multiselect-menu-inner-item")
    # items read "Bottoms Default Category / Men"; "Women" contains "Men", so match the path
    chosen = items.having_text(category).having_text(f"/ {gender}") if gender else items.nth(0)
    yield Click(chosen)
    yield Click(Locator.css(f"{widget} button").having_text("Done"))
    yield from save_product()
    return ""


MATRIX = "[data-index='configurable-matrix'] tbody tr"
WIZARD = "aside.modal-slide._show"
SIZE_ATTRIBUTE_GRID = "/catalog/product_attribute/index/filter/YXR0cmlidXRlX2NvZGU9c2l6ZQ==/"
SWATCH_PANEL = "#swatch-text-options-panel"


@dataclass(frozen=True)
class Combo:
    size: str
    color: str

    @property
    def label(self) -> str:
        return f"Size: {self.size}, Color: {self.color}"


def parse_matrix(snapshot: PageSnapshot) -> tuple[list[Combo], str, str]:
    combos = []
    price = quantity = ""
    for tr in snapshot.css(MATRIX):
        c = [" ".join(td.text_content().split()) for td in tr.cssselect("td")]
        if len(c) < 8:
            continue
        m = re.search(r"Size: ([^,]+), Color: (\S+)", c[7])
        if m is None:
            continue
        combos.append(Combo(m.group(1).strip(), m.group(2)))
        price, quantity = price or c[3].lstrip("$"), quantity or c[4]
    if not combos:
        raise Postcondition(f"no configurations on {snapshot.url}")
    return combos, price, quantity


def _values(text: str) -> list[str]:
    return [v.strip() for v in re.split(r"\s*(?:,|\band\b)\s*", text) if v.strip()]


def _wanted(option: str, value: str, base_setting: str, existing: list[Combo]) -> set[Combo]:
    sizes = list(dict.fromkeys(c.size for c in existing))
    colors = list(dict.fromkeys(c.color for c in existing))
    base = base_setting.lower()
    if option.lower() == "color":
        new_colors = [v.capitalize() for v in _values(value)]
        chosen = sizes if "all" in base else _values(re.sub(r"(?i)\bsizes?\b", "", base))
        return {
            Combo(s.upper() if s.upper() in {x.upper() for x in sizes} else s, c)
            for s in chosen
            for c in new_colors
        }
    new_sizes = [v.upper() for v in _values(value)]
    chosen_colors = (
        colors if "all" in base else [v.capitalize() for v in _values(base) if v.lower() in COLORS]
    )
    return {Combo(s, c) for s in new_sizes for c in chosen_colors}


def _add_size_option(value: str) -> Skill[None]:
    snapshot = yield Goto(f"{site_url('SHOPPING_ADMIN')}{SIZE_ATTRIBUTE_GRID}")
    rows = [
        tr for tr in snapshot.css("table tbody tr") if tr.text_content().split()[:1] == ["size"]
    ]
    if not rows or not rows[0].get("title"):
        raise Postcondition("the size attribute is not in the attribute grid")
    yield Goto(str(rows[0].get("title")))
    yield Click(Locator.css("#add_new_swatch_text_option_button"))
    new_row = f"{SWATCH_PANEL} input[name^='{{}}[value][option_'][name$='][0]']"
    yield Type(Locator.css(new_row.format("swatchtext")), value)
    yield Type(Locator.css(new_row.format("optiontext")), value)
    snapshot = yield Click(Locator.css("button[data-ui-id='attribute-edit-content-save-button']"))
    if "You saved the product attribute" not in snapshot.html:
        snapshot = yield Hover(Locator.css("body"))
    if "You saved the product attribute" not in snapshot.html:
        raise Postcondition(f"size option {value!r} not saved, at {snapshot.url}")


def _wizard_values(product_id: int) -> Skill[PageSnapshot]:
    yield Goto(edit_url(product_id))
    yield Click(Locator.role("button", name="Edit Configurations"))
    return (yield from _next())


def _next() -> Skill[PageSnapshot]:
    return (yield Click(Locator.css(f"{WIZARD} button").having_text("Next")))


def add_variants(option: str, value: str, base_setting: str, product: str) -> Skill[str]:
    spec = parse_spec(product)
    rows = yield from find_products(spec.words)
    parent = catalog_product(rows, spec)
    snapshot = yield Goto(edit_url(parent.product_id))
    existing, price, quantity = parse_matrix(snapshot)
    wanted = _wanted(option, value, base_setting, existing)
    if not wanted:
        raise Precondition(f"nothing to add for {option} {value!r} to {base_setting!r}")
    attribute = option.capitalize()
    new_values = sorted({c.color if attribute == "Color" else c.size for c in wanted})
    entity = f"{WIZARD} .attribute-entity[data-attribute-title='{attribute}']"

    def item(new_value: str) -> str:
        return f"{entity} li.attribute-option[data-attribute-option-title='{new_value}']"

    yield Click(Locator.role("button", name="Edit Configurations"))
    snapshot = yield from _next()
    absent = [v for v in new_values if not snapshot.css(item(v))]
    if absent and attribute != "Size":
        raise Precondition(f"{absent[0]!r} is not an option of {attribute}")
    if absent:
        for new_value in absent:
            yield from _add_size_option(new_value)
        snapshot = yield from _wizard_values(parent.product_id)
        if any(not snapshot.css(item(v)) for v in absent):
            raise Postcondition(f"{absent[0]!r} is still not an option of Size")
    for new_value in new_values:
        yield Click(Locator.css(f"{item(new_value)} label"))
    other = "Color" if attribute == "Size" else "Size"
    have = {c.color if other == "Color" else c.size for c in existing}
    for extra in sorted({c.color if other == "Color" else c.size for c in wanted} - have):
        entity_other = f"{WIZARD} .attribute-entity[data-attribute-title='{other}']"
        option = f"{entity_other} li.attribute-option[data-attribute-option-title='{extra}']"
        if not snapshot.css(option):
            raise Precondition(f"{extra!r} is not an option of {other}")
        yield Click(Locator.css(f"{option} label"))
    yield from _next()
    yield Click(Locator.css(f"{WIZARD} label[for='apply-single-price-radio']"))
    yield Type(Locator.css(f"{WIZARD} #apply-single-price-input"), price)
    yield Click(Locator.css(f"{WIZARD} label[for='apply-single-inventory-radio']"))
    yield Type(Locator.css(f"{WIZARD} #apply-single-inventory-input"), quantity)
    yield from _next()
    snapshot = yield Click(Locator.css(f"{WIZARD} button").having_text("Generate Products"))
    generated, _, _ = parse_matrix(snapshot)
    # the wizard pairs the new value with every existing one; the pairs the task did not ask for go
    for combo in generated:
        if combo in existing or combo in wanted:
            continue
        row = Locator.css(MATRIX).having_text(combo.label)
        yield Click(row.inside("button").having_text("Select"))
        yield Click(row.inside("li").having_text("Remove Product"))
    snapshot = yield from save_product()
    section = snapshot.text("[data-index='configurable']") or ""
    missing = [c for c in wanted if f"-{c.size}-{c.color}" not in section]
    if missing:
        raise Postcondition(f"saved without {missing[0].label}")
    return ""


def quote_positive_reviews(product: str) -> Skill[str]:
    spec = parse_spec(product)
    rows = yield from find_products(spec.words)
    parent = catalog_product(rows, spec)
    reviews = yield from product_reviews(parent.base_name)
    rated = yield from stars_for(reviews)
    quotes = [" ".join(r.detail.split()) for r in rated if r.stars >= POSITIVE]
    if not quotes:
        raise Precondition(f"no positive reviews of {parent.base_name!r}")
    text = "What our customers say: " + " ".join(f'"{q}"' for q in quotes)
    snapshot = yield Goto(edit_url(parent.product_id))
    section = "[data-index='content'] .fieldset-wrapper-title"
    if not snapshot.css(f"{section}[data-state-collapsible='open']"):
        yield Click(Locator.css(section))
    yield Click(Locator.role("button", name="Show / Hide Editor"))
    yield from replace_text(Locator.css("textarea#product_form_short_description"), text)
    yield from save_product()
    return ""


REGISTRY["shopping_admin.new_simple_product"] = new_simple_product
REGISTRY["shopping_admin.quote_positive_reviews"] = quote_positive_reviews
REGISTRY["shopping_admin.add_variants"] = add_variants
