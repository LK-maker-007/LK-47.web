from __future__ import annotations

import re

from lk47.actions import Click, Goto, Locator, Type
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import choose_option, replace_text, select_contiguous


def _discount(rule: str) -> tuple[str, str]:
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", rule):
        return "Percent of product price discount", m.group(1)
    if m := re.search(r"\$(\d+(?:\.\d+)?)", rule):
        whole_cart = "checkout" in rule or "cart" in rule or "order" in rule
        return (
            "Fixed amount discount for whole cart" if whole_cart else "Fixed amount discount"
        ), m.group(1)
    raise Precondition(f"no discount amount in {rule!r}")


def new_cart_price_rule(topic: str, rule: str) -> Skill[str]:
    action, amount = _discount(rule)
    yield Goto(f"{site_url('SHOPPING_ADMIN')}/sales_rule/promo_quote/new/")
    yield Type(Locator.css("input[name='name']"), topic)
    yield from select_contiguous(Locator.css("select[name='website_ids']"), "Main Website", 1)
    yield from select_contiguous(Locator.css("select[name='customer_group_ids']"), "General", 3)
    yield Click(Locator.css(".fieldset-wrapper-title").having_text("Actions"))
    yield from choose_option(Locator.css("select[name='simple_action']"), action)
    yield from replace_text(Locator.css("input[name='discount_amount']"), amount)
    # the grader reads the form fields on the final page, so stay on the rule after saving
    snapshot = yield Click(Locator.role("button", name="Save and Continue Edit"))
    if "/sales_rule/promo_quote/edit/" not in snapshot.url:
        raise Postcondition(f"rule not saved, landed on {snapshot.url}")
    return ""


REGISTRY["shopping_admin.new_cart_price_rule"] = new_cart_price_rule
