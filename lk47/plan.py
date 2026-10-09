from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from lk47.intents import Task


class AnswerKind(Enum):
    EXACT = "exact_match"
    MUST_INCLUDE = "must_include"
    FUZZY = "fuzzy_match"
    NONE = "none"


@dataclass(frozen=True)
class SkillCall:
    name: str
    args: Mapping[str, str]
    # values fixed by the template text itself, such as the date in "Today is 3/15/2023"
    literals: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    template_id: int
    calls: tuple[SkillCall, ...]
    answer: AnswerKind
    budget: int
    final_url: str | None


class NoPlan(LookupError):
    pass


Planner = Callable[[Task], Plan]


def _best_selling(task: Task) -> Plan:
    period_slot = "year" if "year" in task.slots else "period"
    if "brand" in task.text:
        call = SkillCall("shopping_admin.top_brand", {"period": period_slot})
    elif "product type" in task.text:
        call = SkillCall("shopping_admin.top_product_type", {"period": period_slot})
    else:
        call = SkillCall("shopping_admin.top_products", {"n": "n", "period": period_slot})
    answer = AnswerKind.EXACT if task.slots["n"].raw == "1" else AnswerKind.MUST_INCLUDE
    return Plan(279, (call,), answer, budget=3, final_url=None)


def _price_rule(task: Task) -> Plan:
    call = SkillCall("shopping_admin.new_cart_price_rule", {"topic": "topic", "rule": "rule"})
    return Plan(258, (call,), AnswerKind.NONE, budget=14, final_url="/sales_rule/promo_quote/edit/")


def _new_product(task: Task) -> Plan:
    call = SkillCall(
        "shopping_admin.new_simple_product",
        {
            "product": "product",
            "stock": "stock",
            "size": "size",
            "color": "color",
            "price": "price",
        },
    )
    return Plan(256, (call,), AnswerKind.NONE, budget=16, final_url="/catalog/product/edit/id/")


def _single(
    template_id: int, skill: str, args: dict[str, str], answer: AnswerKind, budget: int
) -> Planner:
    def planner(task: Task) -> Plan:
        return Plan(template_id, (SkillCall(skill, args),), answer, budget, None)

    return planner


def _aspects(task: Task) -> Plan:
    keep = "dislike" if task.template_id == 249 else "like"
    if "title and rating" in task.text:
        call = SkillCall("shopping_admin.rated_titles", {"product": "product"}, {"keep": keep})
        return Plan(task.template_id, (call,), AnswerKind.MUST_INCLUDE, 28, None)
    call = SkillCall(f"shopping_admin.{keep}d_aspects", {"product": "product"})
    return Plan(task.template_id, (call,), AnswerKind.FUZZY, 28, None)


def _downvoted(task: Task) -> Plan:
    name = (
        "latest_post_downvotes" if "not from the author" in task.text else "downvoted_comment_count"
    )
    call = SkillCall(f"reddit.{name}", {"forum": "forum"})
    return Plan(33, (call,), AnswerKind.MUST_INCLUDE, 16, None)


def _borders(task: Task) -> Plan:
    name = "map.border_relations" if "relation ID" in task.text else "map.borders"
    return Plan(67, (SkillCall(name, {"state": "state"}),), AnswerKind.MUST_INCLUDE, 30, None)


def _payment(task: Task) -> Plan:
    if "status_1" in task.slots:
        call = SkillCall(
            "shopping_admin.payment_difference",
            {"N": "N", "status_1": "status_1", "status_2": "status_2"},
        )
    elif "status" in task.slots:
        call = SkillCall("shopping_admin.total_payment", {"N": "N", "status": "status"})
    elif m := re.search(
        r"difference between the last (\d+) (.+?) orders and the last \d+ (.+?) orders", task.text
    ):
        literals = {"N": m.group(1), "status_1": m.group(2), "status_2": m.group(3)}
        call = SkillCall("shopping_admin.payment_difference", {}, literals)
    elif m := re.search(r"amount of the last (\d+) (.+?) orders", task.text):
        literals = {"N": m.group(1), "status": m.group(2)}
        call = SkillCall("shopping_admin.total_payment", {}, literals)
    else:
        raise NoPlan("template 367 wording without a count and a status")
    return Plan(367, (call,), AnswerKind.MUST_INCLUDE, 5, None)


def _restock(task: Task) -> Plan:
    if "arrival_phrase" in task.slots:
        phrase = task.slots["arrival_phrase"].raw
        delivery = re.sub(r"^We've received |\s+arrived$", "", phrase)
        call = SkillCall("shopping_admin.restock", {}, {"quantity": delivery})
        return Plan(241, (call,), AnswerKind.NONE, 30, None)
    args = {"quantity": "quantity"}
    if "product" in task.slots:
        args["product"] = "product"
    return Plan(241, (SkillCall("shopping_admin.restock", args),), AnswerKind.NONE, 30, None)


def _under_price(task: Task) -> Plan:
    price = re.sub(r"^under\s*", "", task.slots["price"].raw)
    call = SkillCall(
        "shopping.category_under_price", {"product_category": "product_category"}, {"price": price}
    )
    return Plan(139, (call,), AnswerKind.NONE, 3, None)


def _order_status(task: Task) -> Plan:
    status = task.slots["status"].raw
    status = re.sub(r'^marked as "?(.+?)"?$', r"\1", status)
    status = re.sub(r"^that is not (\w+)$", r"non-\1", status)
    call = SkillCall("shopping.latest_order_total", {}, {"status": status})
    return Plan(214, (call,), AnswerKind.MUST_INCLUDE, 2, None)


MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _today(text: str) -> str | None:
    m = re.search(r"[Tt]oday is (\d{1,2}/\d{1,2}/\d{4})", text)
    if m is not None:
        return m.group(1)
    m = re.search(r"[Tt]oday is ([A-Za-z]+) (\d{1,2}), (\d{4})", text)
    if m is None or m.group(1).lower() not in MONTH_NAMES:
        return None
    return f"{MONTH_NAMES.index(m.group(1).lower()) + 1}/{m.group(2)}/{m.group(3)}"


def _report_for_span(task: Task) -> Plan:
    today = _today(task.text)
    if today is None:
        raise NoPlan("template 268 without its date")
    call = SkillCall(
        "shopping_admin.report_for_span",
        {"report": "report", "time_span": "time_span"},
        {"today": today},
    )
    return Plan(268, (call,), AnswerKind.NONE, 5, None)


def _customers_by_orders(task: Task) -> Plan:
    if "order_criteria" in task.slots:
        criteria = task.slots["order_criteria"].raw
        m = re.search(r"\b(\d+) orders", criteria)
        literals = {"number": m.group(1)} if m else {"quantifier": criteria}
        if "any state" in criteria:
            literals["any_state"] = "yes"
        call = SkillCall("shopping_admin.customers_by_orders", {}, literals)
        return Plan(276, (call,), AnswerKind.MUST_INCLUDE, 6, None)
    args = {"number": "number"} if "number" in task.slots else {"quantifier": "quantifier"}
    call = SkillCall("shopping_admin.customers_by_orders", args)
    return Plan(276, (call,), AnswerKind.MUST_INCLUDE, 6, None)


def _search_terms(task: Task) -> Plan:
    answer = AnswerKind.EXACT if task.slots["n"].raw == "1" else AnswerKind.MUST_INCLUDE
    return Plan(285, (SkillCall("shopping_admin.top_search_terms", {"n": "n"}),), answer, 2, None)


def _fulfilled(task: Task) -> Plan:
    today = _today(task.text)
    if today is None:
        raise NoPlan("template 197 without its date")
    call = SkillCall("shopping.fulfilled_orders", {"period": "period"}, {"today": today})
    return Plan(197, (call,), AnswerKind.FUZZY, 2, None)


NO_SHIPPING = re.compile(r"excluding shipping|without considering shipping", re.I)


def _spend(task: Task) -> Plan:
    if "20% discount" in task.text:
        call = SkillCall("shopping.discounted_spend", {"time": "time"})
        return Plan(147, (call,), AnswerKind.MUST_INCLUDE, 2, None)
    if NO_SHIPPING.search(task.text):
        call = SkillCall("shopping.spend", {"time": "time"}, {"shipping": "exclude"})
        return Plan(147, (call,), AnswerKind.MUST_INCLUDE, 40, None)
    return Plan(
        147, (SkillCall("shopping.spend", {"time": "time"}),), AnswerKind.MUST_INCLUDE, 2, None
    )


def _category_spend(task: Task) -> Plan:
    literals = {"shipping": "exclude"} if NO_SHIPPING.search(task.text) else {}
    call = SkillCall("shopping.category_spend", {"category": "category", "time": "time"}, literals)
    return Plan(162, (call,), AnswerKind.MUST_INCLUDE, 16, None)


def _refund(task: Task) -> Plan:
    literals = {}
    if "only kept" in task.text:
        literals["keep"] = "AC-DC Adapter"
    if "cannot get the shipping fee" in task.text:
        literals["shipping"] = "kept"
    call = SkillCall("shopping.refund", {"time": "time"}, literals)
    return Plan(160, (call,), AnswerKind.MUST_INCLUDE, 12, None)


def _refund_form(task: Task) -> Plan:
    # the reason is written as the intent states it ("it broke after just three days of use")
    m = re.search(r"it broke after [^.\"]+", task.text, re.I)
    if m is None:
        raise NoPlan(f"template {task.template_id} wording without a reason")
    literals = {"reason": m.group(0)}
    if task.template_id == 153:
        args = {"product": "product", "order_id": "order_id"}
        return Plan(
            153, (SkillCall("shopping.refund_message", args, literals),), AnswerKind.NONE, 6, None
        )
    args = {"product": "product", "time": "time"}
    return Plan(
        154, (SkillCall("shopping.refund_draft", args, literals),), AnswerKind.NONE, 14, None
    )


def _brand_reviewers(task: Task) -> Plan:
    # the two wordings of 1356 and 666 name the brand and product type in the template text
    literals = {"brand": "EYZUTAK", "product_type": "phone cases"}
    if "stars" in task.slots:
        call = SkillCall("shopping.brand_reviewers", {"stars": "stars"}, literals)
    else:
        topic = "quality" if "quality" in task.text else "looking"
        call = SkillCall("shopping.brand_reviewers_saying", {}, {**literals, "topic": topic})
    return Plan(task.template_id, (call,), AnswerKind.MUST_INCLUDE, 24, None)


def _brand_products(task: Task) -> Plan:
    # the four wordings of 204 name a product kind and a brand in the template text itself
    text = task.text
    m = re.search(r"names of (.+?) from (\w+)", text)
    if m is not None:
        phrase, brand = m.group(1), m.group(2)
        query = f"{brand} {phrase}"
    else:
        m = re.search(r"names of (.+?),", text)
        if m is None:
            raise NoPlan("template 204 wording without a product phrase")
        phrase = re.sub(r"\s+designed for\s+", " ", m.group(1))
        brand, query = phrase.split()[0], phrase
    call = SkillCall("shopping.brand_products", {}, {"query": query, "brand": brand})
    return Plan(204, (call,), AnswerKind.MUST_INCLUDE, 4, None)


def _remedy(task: Task) -> Plan:
    m = re.search(r"I have (?:a |an )?(.+?) problem", task.text)
    if m is None:
        raise NoPlan("template 151 wording without a problem phrase")
    call = SkillCall("shopping.remedy_search", {}, {"problem": m.group(1)})
    return Plan(151, (call,), AnswerKind.NONE, 2, None)


def _released(task: Task) -> Plan:
    m = re.search(
        r"(?:models of (.+?)|most recent (.+?) models) released between (\d{4})\s*-\s*(\d{4})",
        task.text,
    )
    if m is None:
        raise NoPlan("template 210 wording without a product and years")
    literals = {"product": m.group(1) or m.group(2), "first": m.group(3), "last": m.group(4)}
    call = SkillCall("shopping.released_between", {}, literals)
    return Plan(210, (call,), AnswerKind.NONE, 10, None)


def _reply(task: Task) -> Plan:
    position = task.slots["position_description"].raw.lower()
    if "location" in task.slots:
        position = f"{position} {task.slots['location'].raw.lower()}"
    if "first reply" in position or "first comment" in position:
        name = "reddit.reply_to_first_comment"
    elif position.strip() in ("the post", "this post", "the submission") or position.startswith(
        ("the post on this page", "this post on this page")
    ):
        name = "reddit.reply_to_post"
    else:
        call = SkillCall(
            "reddit.reply_to_role",
            {"role": "position_description", "content": "content_description"},
        )
        return Plan(23, (call,), AnswerKind.NONE, 6, None)
    call = SkillCall(name, {"content": "content_description"})
    return Plan(23, (call,), AnswerKind.NONE, 5, None)


def _top_posts(task: Task) -> Plan:
    description = task.slots["description"].raw
    m = re.search(r"talks? about (.+?)\?", description)
    if m is None:
        raise NoPlan("template 17 wording that needs a reading of each post")
    call = SkillCall(
        "reddit.organizations_in_top",
        {"number": "number", "subreddit": "subreddit"},
        {"topic": m.group(1)},
    )
    return Plan(17, (call,), AnswerKind.MUST_INCLUDE, 14, None)


def _field_help(task: Task) -> Plan:
    m = re.search(r"[Ww]hat could (.+?) help", task.text)
    if m is None:
        raise NoPlan("template 19 wording without a helper phrase")
    call = SkillCall("reddit.field_help", {"subreddit": "subreddit"}, {"helper": m.group(1)})
    return Plan(19, (call,), AnswerKind.NONE, 6, None)


def _advice(task: Task) -> Plan:
    m = re.search(r"in a subreddit for (\w+)", task.text)
    phrase = m.group(1) if m else "relationships"
    call = SkillCall("reddit.ask_advice", {"issue": "issue"}, {"forum_phrase": phrase})
    return Plan(12, (call,), AnswerKind.NONE, 6, None)


def _dislike_user_submissions(task: Task) -> Plan:
    call = SkillCall(
        "reddit.vote_user_submissions", {"user": "user", "subreddit": "subreddit"}, {"up": "no"}
    )
    return Plan(1510, (call,), AnswerKind.NONE, 28, None)


def _license(task: Task) -> Plan:
    call = SkillCall("gitlab.set_license", {"repo": "repo"}, {"license": task.text})
    return Plan(355, (call,), AnswerKind.NONE, 46, None)


def _new_project(task: Task) -> Plan:
    scope = re.search(r"\b(public|private|internal)\b", task.text)
    kind = re.search(r"Create an? (?:public|private|internal) (\S+) repository called", task.text)
    if "template" in task.slots or kind is not None:
        args = {"project_name": "project_name"}
        literals = {"scope": scope.group(1) if scope else "private"}
        if "template" in task.slots:
            args["template"] = "template"
        elif kind is not None:
            literals["template"] = kind.group(1)
        call = SkillCall("gitlab.new_template_project", args, literals)
        return Plan(task.template_id, (call,), AnswerKind.NONE, 16, None)
    args = {"project_name": "project_name"} if "project_name" in task.slots else {}
    literals = {}
    if "project_name" not in task.slots:
        m = re.search(r'project "([^"]+)"', task.text)
        if m is None:
            raise NoPlan("template 332 wording without a quoted project name")
        literals["project_name"] = m.group(1)
    if "scope" in task.slots:
        args["scope"] = "scope"
    elif scope is not None:
        literals["scope"] = scope.group(1)
    if "account_list" in task.slots:
        args["account_list"] = "account_list"
    elif members := re.search(r"and add (.+?) as members", task.text):
        literals["account_list"] = members.group(1)
    call = SkillCall("gitlab.new_project", args, literals)
    # creating takes 4 actions and each member 6 (user search, members page, invite dialog)
    return Plan(task.template_id, (call,), AnswerKind.NONE, 30, None)


def _assign_issue(task: Task) -> Plan:
    if "repo" not in task.slots:
        raise NoPlan("template 999 wording without a repository")
    args = {"issue": "issue", "repo": "repo", "account": "account"}
    return Plan(999, (SkillCall("gitlab.assign_issue", args),), AnswerKind.NONE, 24, None)


def _commits_on(task: Task) -> Plan:
    args = {"user": "user", "date_text": "date"}
    if "repo" in task.slots:
        args["repo"] = "repo"
    return Plan(
        task.template_id, (SkillCall("gitlab.commits_on", args),), AnswerKind.MUST_INCLUDE, 10, None
    )


def _reachable(task: Task) -> Plan:
    m = re.search(r"\bin (\w+) can be reached", task.text)
    if m is None:
        raise NoPlan("template 77 without its town")
    call = SkillCall(
        "map.reachable_in_hour", {"place": "place", "location": "location"}, {"town": m.group(1)}
    )
    return Plan(77, (call,), AnswerKind.MUST_INCLUDE, 30, None)


def _from_here(task: Task) -> Plan:
    m = re.search(r"I am at (.+?), how long", task.text)
    if m is None:
        raise NoPlan("template 35 without its start")
    modes = "car" if re.search(r"\bdrive\b", task.text) else "foot car bike"
    call = SkillCall(
        "map.nearest_by_modes", {"location": "location"}, {"start": m.group(1), "modes": modes}
    )
    return Plan(35, (call,), AnswerKind.FUZZY, 30, None)


def _city_to_city(task: Task) -> Plan:
    m = re.search(r"from (.+?) to (.+?) by car", task.text)
    if m is None:
        raise NoPlan("template 47 without its cities")
    call = SkillCall("map.drive_time", {}, {"start": m.group(1), "end": m.group(2)})
    return Plan(47, (call,), AnswerKind.FUZZY, 20, None)


def _national_park(task: Task) -> Plan:
    call = SkillCall("map.national_park", {"city_description": "city"}, {"question": task.text})
    answer = AnswerKind.EXACT if "?" not in task.text.partition("?")[2] else AnswerKind.MUST_INCLUDE
    return Plan(85, (call,), answer, 30, None)


def _arriving(task: Task) -> Plan:
    m = re.search(
        r"arriving at (.+?)\. Find the nearby (.+?) and the walking distance to the nearest "
        r"(.+?) from",
        task.text,
    )
    if m is None:
        raise NoPlan("template 781 without its places")
    literals = {"start": m.group(1), "first": m.group(2), "second": m.group(3)}
    return Plan(781, (SkillCall("map.chain_walk", {}, literals),), AnswerKind.FUZZY, 30, None)


def _hotel_shops(task: Task) -> Plan:
    m = re.search(
        r"arriving at (.+?)\. (?:Show me the name of|Find if there is) an? (.+?) "
        r"(?:if there is any )?nearby\..*?names of (?:any )?(.+?) that are within (\d+) ?"
        r"min(?:ute)?s (\w+)",
        task.text,
    )
    if m is None:
        raise NoPlan("template 782 without its places")
    literals = {
        "place": m.group(1),
        "target1": m.group(2),
        "target2": m.group(3),
        "minutes": m.group(4),
        "mode": m.group(5),
    }
    call = SkillCall("map.hotel_and_shops_within", {}, literals)
    return Plan(782, (call,), AnswerKind.MUST_INCLUDE, 40, None)


PLANS: dict[int, Planner] = {
    84: _single(
        84,
        "cross.urls_file",
        {"directory": "directory", "gitlab_repo": "gitlab_repo", "subreddit": "subreddit"},
        AnswerKind.FUZZY,
        26,
    ),
    88: _single(88, "cross.readme_repo", {"name": "name", "num": "num"}, AnswerKind.NONE, 44),
    101: _single(
        101,
        "cross.review_feedback_post",
        {"product": "product", "rating": "rating"},
        AnswerKind.NONE,
        10,
    ),
    116: _single(116, "cross.repo_post", {"topic": "topic"}, AnswerKind.NONE, 9),
    117: _single(
        117, "cross.promote_repo", {"repo": "repo", "subreddit": "subreddit"}, AnswerKind.NONE, 9
    ),
    289: _single(
        289,
        "gitlab.starred_repositories",
        {"description": "description"},
        AnswerKind.MUST_INCLUDE,
        2,
    ),
    290: _single(290, "gitlab.merge_requests_assigned", {}, AnswerKind.NONE, 1),
    291: _single(291, "gitlab.merge_requests_to_review", {}, AnswerKind.NONE, 1),
    292: _new_project,
    293: _single(
        293,
        "gitlab.invite_collaborators",
        {"collaborator_account_list": "collaborator_account_list", "repo": "repo"},
        AnswerKind.NONE,
        36,
    ),
    294: _single(294, "gitlab.invite_guest", {"name": "name"}, AnswerKind.NONE, 10),
    298: _single(298, "gitlab.who_has_access", {"repo": "repo"}, AnswerKind.MUST_INCLUDE, 3),
    299: _single(
        299, "gitlab.open_issues_about", {"description": "description"}, AnswerKind.NONE, 8
    ),
    300: _single(300, "gitlab.recent_open_issues", {}, AnswerKind.NONE, 3),
    303: _single(303, "gitlab.todos", {}, AnswerKind.NONE, 1),
    308: _single(308, "gitlab.set_site_title", {"title": "title"}, AnswerKind.NONE, 12),
    310: _single(310, "gitlab.latest_updated_issue", {"keyword": "keyword"}, AnswerKind.FUZZY, 4),
    312: _single(312, "gitlab.feed_token", {}, AnswerKind.EXACT, 2),
    316: _single(
        316,
        "gitlab.branch_top_contributor",
        {"attribute": "attribute", "branch_name": "branch_name"},
        AnswerKind.MUST_INCLUDE,
        20,
    ),
    320: _commits_on,
    321: _single(
        321,
        "gitlab.commits_during",
        {"user": "user", "period": "period"},
        AnswerKind.MUST_INCLUDE,
        12,
    ),
    322: _commits_on,
    323: _single(323, "gitlab.top_contributor", {"repo": "repo"}, AnswerKind.EXACT, 22),
    324: _single(
        324,
        "gitlab.top_contributors",
        {"attribute": "attribute", "repo": "repo"},
        AnswerKind.MUST_INCLUDE,
        22,
    ),
    325: _single(325, "gitlab.explore", {}, AnswerKind.NONE, 1),
    327: _single(
        327,
        "gitlab.create_issue",
        {"repo": "repo", "issue": "issue", "account": "account", "due": "due"},
        AnswerKind.NONE,
        36,
    ),
    328: _single(328, "gitlab.open_issue", {"issue": "issue", "repo": "repo"}, AnswerKind.NONE, 10),
    329: _single(329, "gitlab.clone_command", {"repo": "repo"}, AnswerKind.EXACT, 3),
    330: _single(330, "gitlab.follow_users", {"account_list": "account_list"}, AnswerKind.NONE, 24),
    331: _single(331, "gitlab.set_homepage", {"url": "url"}, AnswerKind.NONE, 6),
    332: _new_project,
    335: _single(
        335,
        "gitlab.submit_merge_request",
        {
            "source_branch": "source_branch",
            "target_branch": "target_branch",
            "reviewer": "reviewer",
        },
        AnswerKind.NONE,
        30,
    ),
    337: _single(337, "gitlab.discuss_issue", {"feature": "feature"}, AnswerKind.NONE, 5),
    339: _single(
        339,
        "gitlab.create_milestone",
        {"event": "event", "start_date": "start_date", "end_date": "end_date"},
        AnswerKind.NONE,
        8,
    ),
    348: _single(
        348,
        "gitlab.comment_merge_request",
        {"content": "content", "mr": "mr", "repo": "repo"},
        AnswerKind.NONE,
        20,
    ),
    349: _single(
        349, "gitlab.issues_by_label", {"repo": "repo", "label": "label"}, AnswerKind.NONE, 4
    ),
    351: _single(
        351,
        "gitlab.add_members",
        {"repo": "repo", "role": "role", "user_list": "user_list"},
        AnswerKind.NONE,
        30,
    ),
    352: _single(352, "gitlab.fork", {"repo": "repo"}, AnswerKind.NONE, 46),
    355: _license,
    354: _single(354, "gitlab.star_top", {"number": "number"}, AnswerKind.NONE, 20),
    357: _single(357, "gitlab.merge_requests_to_review", {}, AnswerKind.NONE, 1),
    360: _single(360, "gitlab.review_reply", {"topic": "topic"}, AnswerKind.NONE, 5),
    361: _single(361, "gitlab.set_status", {"status": "status"}, AnswerKind.NONE, 6),
    500: _single(500, "gitlab.latest_created_issue", {"keyword": "keyword"}, AnswerKind.EXACT, 4),
    600: _single(
        600, "gitlab.new_group", {"name": "name", "members": "members"}, AnswerKind.NONE, 28
    ),
    999: _assign_issue,
    2100: _single(
        2100,
        "gitlab.new_template_project",
        {"project_name": "project_name", "template": "template", "account_list": "account_list"},
        AnswerKind.NONE,
        34,
    ),
    4: _single(4, "reddit.subscribe_trending", {"subreddit": "subreddit"}, AnswerKind.NONE, 5),
    5: _single(
        5, "reddit.post_question", {"question": "question", "topic": "topic"}, AnswerKind.NONE, 6
    ),
    6: _single(6, "reddit.edit_bio", {"content": "content"}, AnswerKind.NONE, 5),
    7: _single(
        7,
        "reddit.create_forum",
        {"name": "name", "description": "description", "sidebar_list": "sidebar_list"},
        AnswerKind.NONE,
        7,
    ),
    9: _single(9, "reddit.post_review", {"book": "book", "content": "content"}, AnswerKind.NONE, 5),
    11: _single(
        11,
        "reddit.repost_image",
        {"content": "content", "subreddit": "subreddit"},
        AnswerKind.NONE,
        8,
    ),
    12: _advice,
    13: _single(13, "reddit.discussion", {"topic": "topic"}, AnswerKind.NONE, 6),
    15: _single(
        15,
        "reddit.recommendations",
        {"category": "category", "price": "price", "subreddit": "subreddit"},
        AnswerKind.NONE,
        6,
    ),
    16: _single(
        16,
        "reddit.meetup",
        {"interest": "interest", "date": "date", "subreddit": "subreddit"},
        AnswerKind.NONE,
        6,
    ),
    19: _field_help,
    22: _single(22, "reddit.upvote_newest", {"subreddit": "subreddit"}, AnswerKind.NONE, 5),
    17: _top_posts,
    23: _reply,
    24: _single(
        24,
        "reddit.thumbs_down_top",
        {"k": "k", "subreddit": "subreddit"},
        AnswerKind.NONE,
        14,
    ),
    25: _single(
        25,
        "reddit.vote_user_submissions",
        {"user": "user", "subreddit": "subreddit"},
        AnswerKind.NONE,
        28,
    ),
    27: _single(
        27, "reddit.edit_my_post", {"post": "post", "content": "content"}, AnswerKind.NONE, 16
    ),
    33: _downvoted,
    1510: _dislike_user_submissions,
    3765: _single(3765, "reddit.post_question", {"question": "question"}, AnswerKind.NONE, 12),
    6100: _single(
        6100,
        "reddit.recommendations",
        {"category": "category", "price": "price"},
        AnswerKind.NONE,
        6,
    ),
    134: _single(134, "shopping.customer_service_number", {}, AnswerKind.FUZZY, 2),
    135: _single(
        135,
        "shopping.review_summary",
        {"product_type": "product_type", "manufature": "manufature"},
        AnswerKind.FUZZY,
        4,
    ),
    136: _single(136, "shopping.main_criticisms", {}, AnswerKind.MUST_INCLUDE, 4),
    137: _single(
        137,
        "shopping.category_sorted",
        {"product_category": "product_category", "order": "order"},
        AnswerKind.NONE,
        3,
    ),
    138: _single(
        138,
        "shopping.most_expensive_in_category",
        {"product_category": "product_category"},
        AnswerKind.NONE,
        4,
    ),
    139: _under_price,
    145: _single(145, "shopping.cheapest_unit_to_cart", {}, AnswerKind.NONE, 12),
    147: _spend,
    151: _remedy,
    153: _refund_form,
    154: _refund_form,
    156: _single(
        156, "shopping.reorder", {"product": "product", "time": "time"}, AnswerKind.NONE, 28
    ),
    155: _single(
        155,
        "shopping.bought_configuration",
        {"option": "option", "product": "product", "time": "time"},
        AnswerKind.MUST_INCLUDE,
        14,
    ),
    159: _single(159, "shopping.price_range", {"product": "product"}, AnswerKind.MUST_INCLUDE, 6),
    160: _refund,
    161: _single(161, "shopping.first_purchase_date", {}, AnswerKind.FUZZY, 2),
    163: _single(163, "shopping.coupon_request", {"reason": "reason"}, AnswerKind.NONE, 3),
    165: _single(165, "shopping.update_address", {"address": "address"}, AnswerKind.NONE, 18),
    162: _category_spend,
    171: _single(171, "shopping.storage_for_cards", {"num": "num"}, AnswerKind.NONE, 9),
    172: _single(
        172,
        "shopping.buy_best_rated",
        {"product_category": "product_category", "dollar_value": "dollar_value"},
        AnswerKind.NONE,
        18,
    ),
    182: _single(182, "shopping.review_summary", {"product_type": "product"}, AnswerKind.FUZZY, 4),
    188: _single(188, "shopping.discounted_items", {}, AnswerKind.FUZZY, 2),
    169: _single(
        169, "shopping.last_ordered", {"description": "description"}, AnswerKind.FUZZY, 46
    ),
    180: _single(180, "shopping.show_latest_order", {"status": "status"}, AnswerKind.NONE, 3),
    186: _single(186, "shopping.wishlist_product", {"product": "product"}, AnswerKind.NONE, 4),
    189: _single(189, "shopping.wishlist_product", {"product": "product"}, AnswerKind.NONE, 4),
    191: _single(
        191, "shopping.change_delivery_address", {"address": "address"}, AnswerKind.FUZZY, 2
    ),
    193: _single(193, "shopping.latest_order_status", {}, AnswerKind.FUZZY, 3),
    194: _single(
        194,
        "shopping.rate_purchase",
        {"product": "product", "num_star": "num_star", "nickname": "nickname"},
        AnswerKind.NONE,
        28,
    ),
    196: _single(196, "shopping.wishlist_this", {}, AnswerKind.NONE, 2),
    197: _fulfilled,
    199: _single(199, "shopping.subscribe_newsletter", {}, AnswerKind.NONE, 4),
    204: _brand_products,
    206: _single(
        206,
        "shopping.order_info",
        {"info": "info", "order_number": "order_number"},
        AnswerKind.MUST_INCLUDE,
        6,
    ),
    207: _single(
        207,
        "shopping.cheapest_with_capacity",
        {"product": "product", "min_storage": "min_storage"},
        AnswerKind.NONE,
        9,
    ),
    208: _single(
        208,
        "shopping.search_sorted",
        {"product": "product", "sorting_order": "sorting_order"},
        AnswerKind.NONE,
        2,
    ),
    210: _released,
    211: _single(211, "shopping.browse_category", {"category": "category"}, AnswerKind.NONE, 3),
    212: _single(212, "shopping.search", {"keyword": "keyword"}, AnswerKind.NONE, 2),
    213: _single(
        213, "shopping.latest_order_number", {"status": "status"}, AnswerKind.MUST_INCLUDE, 2
    ),
    214: _order_status,
    216: _single(216, "shopping.buy_best_reviewed", {"category": "category"}, AnswerKind.NONE, 18),
    222: _single(
        222,
        "shopping.reviewers_mentioning",
        {"description": "description"},
        AnswerKind.MUST_INCLUDE,
        4,
    ),
    370: _single(370, "shopping.brand_price_range", {"brand": "brand"}, AnswerKind.MUST_INCLUDE, 6),
    666: _brand_reviewers,
    1355: _single(
        1355, "shopping.product_rating", {"product": "product"}, AnswerKind.MUST_INCLUDE, 3
    ),
    1356: _brand_reviewers,
    237: _single(237, "shopping_admin.mark_on_sale", {"brand": "brand"}, AnswerKind.NONE, 12),
    240: _single(
        240,
        "shopping_admin.edit_address",
        {"order_id": "order_id", "address": "address"},
        AnswerKind.NONE,
        20,
    ),
    241: _restock,
    242: _single(
        242, "shopping_admin.disable_product", {"product": "product"}, AnswerKind.NONE, 10
    ),
    243: _single(243, "shopping_admin.approve_positive", {}, AnswerKind.NONE, 32),
    244: _single(
        244,
        "shopping_admin.most_unhappy",
        {"information": "information", "product": "product"},
        AnswerKind.EXACT,
        28,
    ),
    245: _single(
        245,
        "shopping_admin.dissatisfied_customers",
        {"product": "product"},
        AnswerKind.MUST_INCLUDE,
        28,
    ),
    246: _single(
        246, "shopping_admin.delete_reviews", {"review_type": "review_type"}, AnswerKind.NONE, 24
    ),
    247: _single(
        247,
        "shopping_admin.change_price",
        {"action": "action", "amount": "amount"},
        AnswerKind.NONE,
        14,
    ),
    248: _single(
        248, "shopping_admin.count_reviews_by_time", {"time": "time"}, AnswerKind.MUST_INCLUDE, 3
    ),
    249: _aspects,
    250: _aspects,
    255: _single(255, "shopping_admin.show_customers", {}, AnswerKind.NONE, 1),
    256: _new_product,
    258: _price_rule,
    266: _single(266, "shopping_admin.theme_preview", {"name": "name"}, AnswerKind.NONE, 3),
    268: _report_for_span,
    270: _single(270, "shopping_admin.monthly_orders", {"period": "period"}, AnswerKind.FUZZY, 6),
    271: _single(
        271,
        "shopping_admin.report_between",
        {"type": "type", "start_date": "start_date", "end_date": "end_date"},
        AnswerKind.NONE,
        5,
    ),
    274: _single(274, "shopping_admin.invoice_total", {"id": "id"}, AnswerKind.MUST_INCLUDE, 3),
    275: _single(
        275,
        "shopping_admin.cms_page_title",
        {"old_heading": "old-heading", "heading": "heading"},
        AnswerKind.NONE,
        8,
    ),
    276: _customers_by_orders,
    277: _single(
        277,
        "shopping_admin.count_reviews_by_status",
        {"status": "status"},
        AnswerKind.MUST_INCLUDE,
        3,
    ),
    279: _best_selling,
    284: _single(
        284,
        "shopping_admin.add_tracking",
        {"order": "order", "service": "service", "tracking": "tracking"},
        AnswerKind.NONE,
        6,
    ),
    285: _search_terms,
    # a grid left filtered by an earlier task costs two actions to clear before the search
    287: _single(287, "shopping_admin.out_of_stock", {"product": "product"}, AnswerKind.NONE, 14),
    288: _single(
        288, "shopping_admin.count_reviews_by_term", {"term": "term"}, AnswerKind.MUST_INCLUDE, 3
    ),
    364: _single(
        364,
        "shopping_admin.customer_by_phone",
        {"PhoneNum": "PhoneNum"},
        AnswerKind.MUST_INCLUDE,
        4,
    ),
    368: _single(
        368,
        "shopping_admin.low_units",
        {"Attribute": "Attribute", "N": "N"},
        AnswerKind.MUST_INCLUDE,
        8,
    ),
    742: _single(
        742,
        "shopping_admin.change_config_price",
        {"action": "action", "config": "config", "amount": "amount"},
        AnswerKind.NONE,
        30,
    ),
    1001: _single(1001, "shopping_admin.frequent_search_brands", {}, AnswerKind.MUST_INCLUDE, 2),
    366: _single(
        366,
        "shopping_admin.order_attribute",
        {"attribute": "attribute", "status": "status"},
        AnswerKind.EXACT,
        8,
    ),
    367: _payment,
    1002: _single(1002, "shopping_admin.items_sold", {"k": "k"}, AnswerKind.MUST_INCLUDE, 12),
    234: _single(
        234, "shopping_admin.most_cancellations", {"attribute": "attribute"}, AnswerKind.EXACT, 8
    ),
    257: _single(257, "shopping_admin.cancel_order", {"id": "id"}, AnswerKind.NONE, 4),
    280: _single(
        280,
        "shopping_admin.notify_customer",
        {"name": "name", "message": "message"},
        AnswerKind.NONE,
        12,
    ),
    251: _single(
        251, "shopping_admin.quote_positive_reviews", {"product": "product"}, AnswerKind.NONE, 28
    ),
    252: _single(
        252,
        "shopping_admin.add_variants",
        {
            "option": "option",
            "value": "value",
            "base_setting": "base_setting",
            "product": "product",
        },
        AnswerKind.NONE,
        48,
    ),
    253: _single(253, "shopping_admin.filter_orders", {"status": "status"}, AnswerKind.NONE, 6),
    73: _single(73, "map.compare_times", {"start": "start", "end": "end"}, AnswerKind.FUZZY, 24),
    77: _reachable,
    68: _single(68, "map.walk_time", {"start": "start", "end": "end"}, AnswerKind.FUZZY, 30),
    69: _single(
        69, "map.closest", {"place1": "place1", "place2": "place2"}, AnswerKind.MUST_INCLUDE, 24
    ),
    64: _single(64, "map.drive_time", {"start": "hotel", "end": "place"}, AnswerKind.FUZZY, 30),
    36: _single(
        36, "map.drive_time", {"start": "location1", "end": "location2"}, AnswerKind.FUZZY, 30
    ),
    46: _single(46, "map.coordinates", {"location": "location"}, AnswerKind.MUST_INCLUDE, 30),
    501: _single(
        501,
        "map.information",
        {"information": "information", "location": "location"},
        AnswerKind.EXACT,
        24,
    ),
    58: _single(
        58,
        "map.walk_distance",
        {"start": "location/address_1", "end": "location/address_2"},
        AnswerKind.EXACT,
        30,
    ),
    52: _single(52, "map.description_page", {"location": "location"}, AnswerKind.NONE, 30),
    59: _single(
        59, "map.search_around", {"space": "space", "location": "location"}, AnswerKind.NONE, 1
    ),
    75: _single(
        75,
        "map.walkway_to_closest",
        {"store": "store", "location": "location"},
        AnswerKind.NONE,
        46,
    ),
    79: _single(
        79,
        "map.airports_within",
        {"airport_type": "airport_type", "radius": "radius", "start": "start"},
        AnswerKind.MUST_INCLUDE,
        30,
    ),
    78: _single(
        78,
        "map.hotel_and_supermarket",
        {
            "place": "place",
            "target1": "target1",
            "information": "information",
            "target2": "target2",
        },
        AnswerKind.MUST_INCLUDE,
        40,
    ),
    70: _single(70, "map.zip_code", {"place": "place"}, AnswerKind.EXACT, 24),
    72: _single(
        72,
        "map.walk_then_drive",
        {"first": "place_A", "second": "place_B", "third": "place_C"},
        AnswerKind.FUZZY,
        40,
    ),
    66: _single(
        66,
        "map.nearest_with_walk",
        {"places": "places", "start": "start"},
        AnswerKind.MUST_INCLUDE,
        30,
    ),
    35: _from_here,
    65: _single(65, "map.best_order", {"place_list": "place_list"}, AnswerKind.FUZZY, 40),
    41: _single(
        41, "map.hotels_within_walk", {"location": "location", "n": "n"}, AnswerKind.FUZZY, 40
    ),
    39: _single(
        39,
        "map.nearest_where",
        {"location": "location", "location2": "location2", "condition": "condition"},
        AnswerKind.MUST_INCLUDE,
        30,
    ),
    54: _single(
        54,
        "map.show_directions",
        {
            "start": "location/address_1",
            "end": "location/address_2",
            "transportation": "transportation",
        },
        AnswerKind.NONE,
        30,
    ),
    47: _city_to_city,
    51: _single(
        51, "map.drive_between", {"city1": "city1", "city2": "city2"}, AnswerKind.FUZZY, 40
    ),
    42: _single(42, "map.route_between", {"city1": "city1", "city2": "city2"}, AnswerKind.NONE, 40),
    85: _national_park,
    94: _single(
        94,
        "map.stadium_route",
        {"location": "location", "sport_team": "sport_team"},
        AnswerKind.NONE,
        30,
    ),
    67: _borders,
    371: _single(371, "map.find_page", {"description": "description"}, AnswerKind.NONE, 40),
    87: _single(
        87, "cross.wiki_readme", {"name": "name", "subject": "topics"}, AnswerKind.NONE, 30
    ),
    781: _arriving,
    782: _hotel_shops,
}


def build(task: Task) -> Plan:
    try:
        planner = PLANS[task.template_id]
    except KeyError:
        raise NoPlan(str(task.template_id)) from None
    return planner(task)
