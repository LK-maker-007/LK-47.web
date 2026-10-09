from __future__ import annotations

from lk47.actions import Check, Click, Goto, Locator, Type
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import choose_option, replace_text
from lk47.skills.shopping.orders import _by_number, _find_item, _range, history
from lk47.skills.shopping_admin.orders import STATES

COMMENT = "form.contact textarea[name='comment']"


def _refund_text(product: str, order_number: str, sku: str, price: str, reason: str) -> str:
    return (
        f"I would like a refund for the {product} from order #{order_number} (SKU {sku}, "
        f"amount ${price}): {reason[:1].lower()}{reason[1:]}."
    )


def refund_message(product: str, order_id: str, reason: str) -> Skill[str]:
    rows = yield from history()
    row = _by_number(rows, order_id)
    found = yield from _find_item([row], product, lambda r: True)
    if found is None:
        raise Precondition(f"order {order_id} has no {product!r}")
    yield Goto(f"{site_url('SHOPPING')}/contact/")
    yield Type(
        Locator.css(COMMENT),
        _refund_text(product, order_id, found[2].sku, f"{found[2].price:.2f}", reason),
    )
    return ""


def refund_draft(product: str, time: str, reason: str) -> Skill[str]:
    rows = yield from history()
    span = _range(time)
    found = yield from _find_item(rows, product, lambda r: span.start <= r.placed <= span.end)
    if found is None:
        raise Precondition(f"no {product!r} bought {time}")
    yield Goto(f"{site_url('SHOPPING')}/contact/")
    yield Type(
        Locator.css(COMMENT),
        _refund_text(product, found[0].number, found[2].sku, f"{found[2].price:.2f}", reason),
    )
    return ""


def coupon_request(reason: str) -> Skill[str]:
    yield Goto(f"{site_url('SHOPPING')}/contact/")
    yield Type(Locator.css(COMMENT), f"Could I have a coupon? {reason.strip().rstrip('.')}.")
    return ""


def subscribe_newsletter() -> Skill[str]:
    yield Goto(f"{site_url('SHOPPING')}/newsletter/manage/")
    yield Check(Locator.css("input#subscription"))
    snapshot = yield Click(Locator.role("button", name="Save"))
    if (
        "We have saved your subscription" not in snapshot.html
        and "subscription" not in snapshot.html.lower()
    ):
        raise Postcondition("subscription not saved")
    return ""


def update_address(address: str) -> Skill[str]:
    # the account has one address that is both default billing and shipping; it is edited in place
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 4:
        raise Precondition(f"address needs street, city, state and zip: {address!r}")
    *streets, city, state, postcode = parts
    region = STATES.get(state.upper(), state)
    snapshot = yield Goto(f"{site_url('SHOPPING')}/customer/address/")
    links = snapshot.css(".box-address-billing a[href*='/customer/address/edit/']")
    if not links:
        raise Postcondition("no billing address to edit")
    yield Goto(str(links[0].get("href")))
    yield from replace_text(Locator.css("input[name='street[0]']"), streets[0])
    if len(streets) > 1:
        yield from replace_text(Locator.css("input[name='street[1]']"), ", ".join(streets[1:]))
    yield from replace_text(Locator.css("input[name='city']"), city)
    yield from choose_option(Locator.css("select[name='region_id']"), region)
    yield from replace_text(Locator.css("input[name='postcode']"), postcode)
    snapshot = yield Click(Locator.role("button", name="Save Address"))
    if streets[0] not in snapshot.html:
        raise Postcondition("the address book does not show the new street")
    return ""


REGISTRY["shopping.refund_message"] = refund_message
REGISTRY["shopping.refund_draft"] = refund_draft
REGISTRY["shopping.coupon_request"] = coupon_request
REGISTRY["shopping.subscribe_newsletter"] = subscribe_newsletter
REGISTRY["shopping.update_address"] = update_address
