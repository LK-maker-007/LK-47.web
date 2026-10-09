from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SlotKind(Enum):
    PRODUCT_NAME = "product_name"
    REPO_PATH = "repo_path"
    SUBREDDIT = "subreddit"
    PLACE_NAME = "place_name"
    PLACE_DESCRIBED = "place_described"
    PERIOD = "period"
    DATE = "date"
    STATUS = "status"
    COUNT = "count"
    MONEY = "money"
    DIRECTION = "direction"
    IDENTIFIER = "identifier"
    PERSON = "person"
    FREE_TEXT = "free_text"
    YEAR = "year"
    ATTRIBUTE = "attribute"
    CONDITION = "condition"
    FORMAT = "format"
    MODIFIER = "modifier"


@dataclass(frozen=True)
class SlotValue:
    kind: SlotKind
    raw: str


SLOT_KINDS: dict[str, SlotKind] = {
    "product": SlotKind.PRODUCT_NAME,
    "product_type": SlotKind.PRODUCT_NAME,
    "brand": SlotKind.PRODUCT_NAME,
    "manufature": SlotKind.PRODUCT_NAME,
    "repo": SlotKind.REPO_PATH,
    "gitlab_repo": SlotKind.REPO_PATH,
    "subreddit": SlotKind.SUBREDDIT,
    "forum": SlotKind.SUBREDDIT,
    "location": SlotKind.PLACE_NAME,
    "location1": SlotKind.PLACE_NAME,
    "location2": SlotKind.PLACE_NAME,
    "start": SlotKind.PLACE_NAME,
    "end": SlotKind.PLACE_NAME,
    "place": SlotKind.PLACE_NAME,
    "places": SlotKind.PLACE_NAME,
    "place1": SlotKind.PLACE_NAME,
    "place2": SlotKind.PLACE_NAME,
    "place_A": SlotKind.PLACE_NAME,
    "place_B": SlotKind.PLACE_NAME,
    "place_C": SlotKind.PLACE_NAME,
    "hotel": SlotKind.PLACE_NAME,
    "store": SlotKind.PLACE_NAME,
    "space": SlotKind.PLACE_NAME,
    "location/address_1": SlotKind.PLACE_NAME,
    "location/address_2": SlotKind.PLACE_NAME,
    "city": SlotKind.PLACE_DESCRIBED,
    "city1": SlotKind.PLACE_DESCRIBED,
    "city2": SlotKind.PLACE_DESCRIBED,
    "sport_team": SlotKind.PLACE_DESCRIBED,
    "time": SlotKind.PERIOD,
    "period": SlotKind.PERIOD,
    "time_span": SlotKind.PERIOD,
    "year": SlotKind.YEAR,
    "date": SlotKind.DATE,
    "start_date": SlotKind.DATE,
    "end_date": SlotKind.DATE,
    "due": SlotKind.DATE,
    "status": SlotKind.STATUS,
    "status_1": SlotKind.STATUS,
    "status_2": SlotKind.STATUS,
    "n": SlotKind.COUNT,
    "N": SlotKind.COUNT,
    "num": SlotKind.COUNT,
    "number": SlotKind.COUNT,
    "k": SlotKind.COUNT,
    "quantity": SlotKind.COUNT,
    "stock": SlotKind.COUNT,
    "num_star": SlotKind.COUNT,
    "rating": SlotKind.FREE_TEXT,
    "min_storage": SlotKind.FREE_TEXT,
    "radius": SlotKind.FREE_TEXT,
    "price": SlotKind.MONEY,
    "amount": SlotKind.MONEY,
    "dollar_value": SlotKind.MONEY,
    "value": SlotKind.FREE_TEXT,
    "action": SlotKind.DIRECTION,
    "order": SlotKind.DIRECTION,
    "sorting_order": SlotKind.DIRECTION,
    "transportation": SlotKind.DIRECTION,
    "id": SlotKind.IDENTIFIER,
    "order_id": SlotKind.IDENTIFIER,
    "order_number": SlotKind.IDENTIFIER,
    "tracking": SlotKind.IDENTIFIER,
    "PhoneNum": SlotKind.IDENTIFIER,
    "url": SlotKind.IDENTIFIER,
    "user": SlotKind.PERSON,
    "account": SlotKind.PERSON,
    "reviewer": SlotKind.PERSON,
    "nickname": SlotKind.PERSON,
    "name": SlotKind.PERSON,
    "members": SlotKind.PERSON,
    "account_list": SlotKind.PERSON,
    "user_list": SlotKind.PERSON,
    "collaborator_account_list": SlotKind.PERSON,
    "description": SlotKind.FREE_TEXT,
    "content": SlotKind.FREE_TEXT,
    "content_description": SlotKind.FREE_TEXT,
    "message": SlotKind.FREE_TEXT,
    "question": SlotKind.FREE_TEXT,
    "title": SlotKind.FREE_TEXT,
    "heading": SlotKind.FREE_TEXT,
    "old-heading": SlotKind.FREE_TEXT,
    "reason": SlotKind.FREE_TEXT,
    "topic": SlotKind.FREE_TEXT,
    "topics": SlotKind.FREE_TEXT,
    "issue": SlotKind.FREE_TEXT,
    "event": SlotKind.FREE_TEXT,
    "position_description": SlotKind.FREE_TEXT,
    "review_type": SlotKind.FREE_TEXT,
    "rule": SlotKind.FREE_TEXT,
    "config": SlotKind.FREE_TEXT,
    "template": SlotKind.FREE_TEXT,
    "feature": SlotKind.FREE_TEXT,
    "book": SlotKind.FREE_TEXT,
    "interest": SlotKind.FREE_TEXT,
    "post": SlotKind.FREE_TEXT,
    "mr": SlotKind.FREE_TEXT,
    "label": SlotKind.FREE_TEXT,
    "keyword": SlotKind.FREE_TEXT,
    "term": SlotKind.FREE_TEXT,
    "service": SlotKind.FREE_TEXT,
    "role": SlotKind.FREE_TEXT,
    "scope": SlotKind.FREE_TEXT,
    "branch_name": SlotKind.FREE_TEXT,
    "source_branch": SlotKind.FREE_TEXT,
    "target_branch": SlotKind.FREE_TEXT,
    "project_name": SlotKind.FREE_TEXT,
    "directory": SlotKind.FREE_TEXT,
    "type": SlotKind.FREE_TEXT,
    "report": SlotKind.FREE_TEXT,
    "information": SlotKind.FREE_TEXT,
    "info": SlotKind.FREE_TEXT,
    "attribute": SlotKind.FREE_TEXT,
    "Attribute": SlotKind.FREE_TEXT,
    "option": SlotKind.FREE_TEXT,
    "base_setting": SlotKind.ATTRIBUTE,
    "color": SlotKind.FREE_TEXT,
    "size": SlotKind.FREE_TEXT,
    "condition": SlotKind.CONDITION,
    "target1": SlotKind.FREE_TEXT,
    "target2": SlotKind.FREE_TEXT,
    "airport_type": SlotKind.FREE_TEXT,
    "place_list": SlotKind.FREE_TEXT,
    "sidebar_list": SlotKind.FREE_TEXT,
    "stars": SlotKind.FREE_TEXT,
    "quantifier": SlotKind.FREE_TEXT,
    "state": SlotKind.FREE_TEXT,
    "address": SlotKind.FREE_TEXT,
    "category": SlotKind.FREE_TEXT,
    "product_category": SlotKind.FREE_TEXT,
}

# Matching is by text bounded by a template's literals, anchored on the whole intent. Slot names
# are overloaded across templates (status holds GitLab status messages, order holds both sort
# directions and order numbers), so most kinds match any text and drive normalization only.
# Kinds that sit next to another slot across a bare space need a shape; each shape below is
# written from the values in the test set and checked by the oracle test.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_NUMBER_WORD = r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
SHAPES: dict[SlotKind, str] = {
    SlotKind.PERIOD: (
        r"(?:(?:in|on|during|durning|over|from|between|around|by|for|each|early|sometime|Quarter)\b.*?"
        rf"|\d{{1,2}}/\d{{4}}-\d{{1,2}}/\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|\d{{4}}(?:/\d{{1,2}})?"
        rf"|{_MONTH} \d{{4}}.*?|)"
    ),
    SlotKind.YEAR: r"\d{4}",
    SlotKind.COUNT: rf"(?:\d+(?:-\d+)?|{_NUMBER_WORD})",
    SlotKind.ATTRIBUTE: r"(?:size .+?|all .+?|[a-z]+(?: and [a-z]+)*)",
    SlotKind.CONDITION: r"(?:(?:I|you|we|if|within|where|when|that|which)\b.*|)",
    SlotKind.FORMAT: r"(?:\.?\s*(?:Return|Use)\b.*|)",
    SlotKind.MODIFIER: r"(?: in total|)",
}

# how specific a shape is; breaks ties between wordings of one template that differ only in the
# slot name they use for the same position (template 279: {{year}} against {{period}})
SPECIFICITY: dict[SlotKind, int] = {
    SlotKind.YEAR: 3,
    SlotKind.COUNT: 3,
    SlotKind.PERIOD: 2,
    SlotKind.ATTRIBUTE: 2,
    SlotKind.CONDITION: 2,
}

NAME_KINDS = frozenset(
    {
        SlotKind.PRODUCT_NAME,
        SlotKind.REPO_PATH,
        SlotKind.SUBREDDIT,
        SlotKind.PLACE_NAME,
        SlotKind.PERSON,
        SlotKind.IDENTIFIER,
    }
)

WORDING_SLOT_KINDS: dict[tuple[int, str], dict[str, SlotKind]] = {
    (241, "We've received {{quantity}}, update the inventory."): {"quantity": SlotKind.FREE_TEXT},
    (248, "How many reviews did our shop receive {{time}}?"): {"time": SlotKind.FREE_TEXT},
}

VERIFIED_SLOT_KINDS: dict[str, SlotKind] = {
    "retrieved_data_format_spec": SlotKind.FORMAT,
    "modifier": SlotKind.MODIFIER,
}
