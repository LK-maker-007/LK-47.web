import re

import pytest

from lk47.actions import (
    NO_ANSWER,
    Act,
    Check,
    Click,
    Goto,
    Hover,
    InvalidAction,
    Locator,
    LocatorCall,
    Press,
    Scroll,
    Select,
    Stop,
    Type,
    render,
    to_harness,
)
from lk47.intents.slots import SHAPES

ACCEPTED: list[tuple[Act, str]] = [
    (Click(Locator.role("button", name="Save")), 'page.get_by_role("button", name="Save").click()'),
    (Click(Locator.css("#search").nth(0)), 'page.locator("#search >> nth=0").click()'),
    (
        Click(Locator.css("a.user").having_text("Rohan").nth(0)),
        'page.locator("a.user").filter(has_text="Rohan").locator("nth=0").click()',
    ),
    (
        Click(Locator.role("row").having_text("302").inside("a")),
        'page.get_by_role("row").filter(has_text="302").locator("a").click()',
    ),
    (
        Type(Locator.css("input[name='from']"), "1/1/2022"),
        'page.locator("input[name=\'from\']").fill("1/1/2022")',
    ),
    (
        Type(Locator.label("Password", exact=True), "x"),
        'page.get_by_label("Password", exact=True).fill("x")',
    ),
    (
        Select(Locator.css("select[name='status']"), "Canceled"),
        'page.locator("select[name=\'status\']").select_option("Canceled")',
    ),
    (Check(Locator.css("#chk")), 'page.locator("#chk").check()'),
    (Hover(Locator.text("Orders")), 'page.get_by_text("Orders").hover()'),
    (
        Goto("http://localhost:7780/admin/sales/order/"),
        'page.goto("http://localhost:7780/admin/sales/order/")',
    ),
    (Press("Control+a"), 'page.press("Control+a")'),
    (Scroll("down"), "page.scroll(down)"),
    (Stop("Quest Lumaflex™ Band"), 'page.stop("Quest Lumaflex™ Band")'),
    (Stop(NO_ANSWER), 'page.stop(" ")'),
    (Stop('He said "hi"'), 'page.stop("He said "hi"")'),
]


@pytest.mark.parametrize(("act", "code"), ACCEPTED, ids=[c for _, c in ACCEPTED])
def test_renders_and_round_trips_through_the_harness(act: Act, code: str) -> None:
    assert render(act) == code
    action = to_harness(act)
    assert action["raw_prediction"] == code
    if isinstance(act, Stop):
        assert action["answer"] == act.answer


def test_type_text_with_a_line_break_is_rejected() -> None:
    with pytest.raises(InvalidAction):
        render(Type(Locator.css("#a"), "x\ny"))


def test_line_breaks_are_rejected() -> None:
    with pytest.raises(InvalidAction):
        render(Type(Locator.css("#a"), "line\nbreak"))
    with pytest.raises(InvalidAction):
        render(Stop("two\nlines"))


def test_empty_stop_is_rejected() -> None:
    with pytest.raises(InvalidAction):
        render(Stop(""))


def test_nth_applies_only_to_css_locators_and_filters() -> None:
    with pytest.raises(InvalidAction):
        Locator.role("link", name="Orders").nth(0)


def test_unlisted_locator_method_is_rejected() -> None:
    with pytest.raises(InvalidAction):
        LocatorCall("nth", ("0",))


def test_slot_shapes_are_valid_regexes() -> None:
    for body in SHAPES.values():
        re.compile(body)


def test_harness_equivalence_distinguishes_our_actions() -> None:
    from browser_env.actions import is_equivalent

    fill_a = to_harness(Type(Locator.css("input[name='name']"), "spring sale"))
    fill_b = to_harness(Type(Locator.css("input[name='discount_amount']"), "20"))
    click_a = to_harness(Click(Locator.css("#x")))
    click_b = to_harness(Click(Locator.css("#y")))
    assert not is_equivalent(fill_a, fill_b)
    assert not is_equivalent(click_a, click_b)
    assert is_equivalent(fill_a, to_harness(Type(Locator.css("input[name='name']"), "spring sale")))
    assert is_equivalent(click_a, to_harness(Click(Locator.css("#x"))))


def test_every_action_renders_its_code_for_the_trajectory() -> None:
    for act in (Goto("http://a.invalid/"), Press("Control+a"), Scroll("down"), Stop("x")):
        assert to_harness(act)["pw_code"] == render(act)


def test_fill_target_cannot_contain_the_word_type() -> None:
    from lk47.actions import InvalidAction, Locator, Type, render

    with pytest.raises(InvalidAction):
        render(Type(Locator.css("select[name='type_id']"), "Simple Product"))
    block = Locator.css(".filters .admin__form-field").having_text("Type").inside("select")
    assert render(Type(block, "Simple Product")) == (
        'page.locator(".filters .admin__form-field").filter(has_text="Type")'
        '.locator("select").fill("Simple Product")'
    )


def test_typed_text_with_quotes_parentheses_and_dots_round_trips() -> None:
    from browser_env.actions import parse_playwright_code

    paragraph = (
        'Permission is granted (the "Software"), to deal; IN NO EVENT. THE SOFTWARE IS '
        'PROVIDED "AS IS", WITHOUT WARRANTY. Copyright (c) 2026 Byte Blaze\u2019s \u2013 ok.'
        " \U0001f916 dotfiles \\ tab\there"
    )
    act = Type(Locator.css(".monaco-editor textarea.inputarea"), paragraph)
    code = to_harness(act)["pw_code"]
    assert parse_playwright_code(code)[-1]["arguments"][0] == paragraph
