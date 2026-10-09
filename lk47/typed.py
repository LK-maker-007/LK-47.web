from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from typing import Any

from lk47.answers import UNACHIEVABLE_ANSWER, Unachievable

# WebArena-Verified grades a typed response instead of the stop text: the kind of result, a
# status, and values typed as the intent's closing note asks. The skills answer in text; the
# shapes below read that text back into the keys the note names.
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
DURATION = re.compile(r"(?:(\d+)\s*h\s*)?(\d+)\s*min|(\d+):(\d{2})\b")
MONTHS = tuple(m.lower() for m in calendar.month_name[1:])

Item = str | int | float | bool | dict[str, Any] | list[Any] | None


def _typed(item: str) -> str | int | float:
    if NUMBER.fullmatch(item) is None or (item.startswith("0") and item[1:2].isdigit()):
        return item
    return float(item) if "." in item else int(item)


def _hms(text: str) -> str:
    m = DURATION.search(text)
    if m is None:
        return text
    hours, minutes = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
    return f"{int(hours or 0):02d}:{int(minutes):02d}:00"


def _date(text: str) -> str | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if m:
        year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        return f"{year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4})", text)
    months = [name[:3] for name in MONTHS]
    if m and m.group(1).lower() in months:
        month = months.index(m.group(1).lower()) + 1
        return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
    return None


def _number(text: str) -> float | str:
    m = NUMBER.search(text.replace(",", ""))
    return float(m.group(0)) if m else text


def _month(text: str) -> str:
    prefix = text.strip().lower()[:3]
    full = next((m for m in MONTHS if m.startswith(prefix)), text.strip())
    return full.capitalize()


def _boolean(text: str, intent: str) -> bool | str:
    lowered = text.lower()
    if "true if closed" in intent:
        return "closed" in lowered or lowered.startswith("yes")
    if lowered.startswith(("yes", "true")):
        return True
    if lowered.startswith(("no", "false")):
        return False
    return text


def _split(value: str) -> list[str]:
    # lists are joined with "; " where an item may hold a comma, with ", " otherwise
    sep = "; " if "; " in value else ", "
    return [i.strip() for i in value.split(sep) if i.strip()]


def _pairs(value: str) -> list[tuple[str, str]]:
    return [(k.strip(), v.strip()) for k, _, v in (i.rpartition(": ") for i in _split(value)) if k]


def _labelled(value: str) -> dict[str, str]:
    found = re.findall(r"([a-z][a-z ]*): (.+?)(?=, [a-z][a-z ]*: |$)", value)
    return {k.replace(" ", "_"): v for k, v in found}


def _range(value: str) -> tuple[float | str, float | str]:
    low, _, high = value.rpartition(" to ")
    return _number(low), _number(high)


def _names_and_range(value: str, keys: list[str]) -> list[Item]:
    names, _, prices = value.partition(". Price range: ")
    low, high = _range(prices)
    return [{"names": _split(names), "min": low, "max": high}]


def _min_max(value: str, keys: list[str]) -> list[Item]:
    low, high = _range(value)
    return [{"min": low, "max": high}]


def _first_then_value(value: str, keys: list[str]) -> list[Item]:
    name, _, rest = value.partition("; ")
    second = _hms(rest) if keys[1] in ("travel_time", "duration") else rest
    first: Item = _typed(name) if keys[0].endswith("_id") else name
    return [{keys[0]: first, keys[1]: second}]


def _named_values(value: str, keys: list[str]) -> list[Item]:
    rows: list[Item] = []
    for name, val in _pairs(value):
        second: Any = val
        if keys[1] in ("duration", "travel_time"):
            second = _hms(val)
        elif keys[1] in ("count", "number_of_commits", "rating"):
            second = _typed(val)
        elif keys[1] in ("total", "price"):
            second = _number(val)
        if keys[0] == "month":
            rows.append({"month": _month(name), keys[1]: second})
        elif keys[:2] == ["first_name", "last_name"]:
            first, _, last = name.partition(" ")
            rows.append({"first_name": first, "last_name": last, keys[2]: second})
        else:
            rows.append({keys[0]: name, keys[1]: second})
    return rows


def _positional(value: str, keys: list[str]) -> list[Item]:
    parts = [p.strip() for p in value.split(", ")]
    return [dict(zip(keys, parts, strict=False))] if len(parts) == len(keys) else [value]


def _by_label(value: str, keys: list[str]) -> list[Item]:
    found = _labelled(value)
    row: dict[str, Any] = {k: found.get(k) for k in keys}
    if "purchase_date" in row and row["purchase_date"]:
        row["purchase_date"] = _date(row["purchase_date"])
    return [row]


# the first three digits of a US postcode and the state they belong to, for the states of the
# map's Northeast extract and their neighbours; the map names no state for Pennsylvania places
ZIP_STATES = (
    (10, 27, "Massachusetts"),
    (28, 29, "Rhode Island"),
    (30, 38, "New Hampshire"),
    (39, 49, "Maine"),
    (50, 59, "Vermont"),
    (60, 69, "Connecticut"),
    (70, 89, "New Jersey"),
    (100, 149, "New York"),
    (150, 196, "Pennsylvania"),
    (197, 199, "Delaware"),
    (206, 219, "Maryland"),
)
STATE_NAMES = frozenset(name for _, _, name in ZIP_STATES)


def _address(display: str) -> dict[str, str | None]:
    parts = [p.strip() for p in display.split(", ")]
    postcode = next((p for p in parts if re.fullmatch(r"\d{5}", p)), None)
    number = next((i for i, p in enumerate(parts) if re.fullmatch(r"\d+[A-Za-z]?", p)), None)
    county = next((i for i, p in enumerate(parts) if p.endswith("County")), None)
    state = next((p for p in parts if p in STATE_NAMES), None)
    if state is None and postcode is not None:
        prefix = int(postcode[:3])
        state = next((name for low, high, name in ZIP_STATES if low <= prefix <= high), None)
    return {
        "name": parts[0],
        "house_number": parts[number] if number is not None else None,
        "street": parts[number + 1] if number is not None and number + 1 < len(parts) else None,
        "city": parts[county - 1] if county else None,
        "state": state,
        "postcode": postcode,
    }


STREET_SUFFIX = (
    r"(?:St|Street|Ave|Avenue|Dr|Drive|Rd|Road|Blvd|Boulevard|Ln|Lane|Way|Ct|Court|Pl|Place"
    r"|Pkwy|Parkway|Ter|Terrace|Cir|Circle|Hwy|Highway)\.?"
)
ADDRESS_BOX = re.compile(
    rf"^(?:.+? )?(?P<house_number>\d+[A-Za-z]?) (?P<street>.+? {STREET_SUFFIX}) (?P<city>.+?), "
    r"(?P<state>[^,]+), (?P<postcode>\d{5}(?:-\d{4})?) (?P<country>.+?)(?: T: .*)?$"
)


def _order_info(value: str, keys: list[str]) -> list[Item]:
    if "house_number" not in keys:
        return _named_values(value, keys)
    m = ADDRESS_BOX.match(value.strip())
    return [{k: m.group(k) for k in keys}] if m else [value]


def _addresses(value: str, keys: list[str]) -> list[Item]:
    return [{k: _address(place).get(k) for k in keys} for place in value.split("; ") if place]


def _fields(value: str, keys: list[str]) -> list[Item]:
    return [dict(zip(keys, (_typed(p) for p in value.split("; ")), strict=False))]


def _order_arrival(value: str, keys: list[str]) -> list[Item]:
    m = re.search(r"order (?:was|is) (\w+)", value)
    return [{"status": m.group(1) if m else value, "arrival_date": _date(value)}]


def _coordinates(value: str, keys: list[str]) -> list[Item]:
    lat, _, lon = value.partition(", ")
    return [{"latitude": _number(lat), "longitude": _number(lon)}]


def _orders_and_amount(value: str, keys: list[str]) -> list[Item]:
    count, _, amount = value.partition(" orders, ")
    return [{"order_count": _typed(count.strip()), "amount": _number(amount)}]


def _hotel_and_shops(value: str, keys: list[str]) -> list[Item]:
    hotel, _, shops = value.partition("; ")
    return [{"hotel": hotel, "supermarkets": [s.strip() for s in shops.split(", ") if s.strip()]}]


def _modes(value: str, keys: list[str]) -> list[Item]:
    modes = {"walk": "Walking", "drive": "Driving", "bike": "Biking"}
    _, _, timings = value.rpartition("; ")
    return [
        {"transportation_method": modes.get(k.lower(), k), "duration": _hms(v)}
        for k, v in _pairs(timings)
    ]


Shape = Callable[[str, list[str]], list[Item]]

SHAPES: dict[int, Shape] = {
    33: _fields,
    35: _modes,
    39: _addresses,
    41: _named_values,
    46: _coordinates,
    73: _named_values,
    78: _first_then_value,
    147: _named_values,
    159: _min_max,
    193: _order_arrival,
    197: _orders_and_amount,
    204: _names_and_range,
    206: _order_info,
    234: _by_label,
    249: _named_values,
    250: _named_values,
    270: _named_values,
    316: _positional,
    324: _named_values,
    364: _positional,
    366: _by_label,
    368: _named_values,
    370: _min_max,
    79: _addresses,
    85: _first_then_value,
    782: _hotel_and_shops,
}


def _keys(intent: str) -> list[str]:
    _, _, note = intent.partition("with key")
    return re.findall(r'"(\w+)"', note)


SINGLE: tuple[tuple[str, Callable[[str, str], Item]], ...] = (
    ("HH:MM:SS", lambda value, intent: _hms(value)),
    ("YYYY-MM-DD", lambda value, intent: _date(value)),
    ("as a number", lambda value, intent: _number(value)),
    ("Return a boolean", _boolean),
    ("Return true if", _boolean),
    ("URL only", lambda value, intent: value.rsplit(maxsplit=1)[-1]),
)


def values(template_id: int | None, value: str, intent: str) -> list[Item]:
    keys = _keys(intent)
    if keys and template_id in SHAPES:
        shape = SHAPES[template_id]
        if template_id == 366 and keys[0] == "name":
            shape = _named_values
        return shape(value, keys)
    convert = next((c for phrase, c in SINGLE if phrase in intent), None)
    if convert is not None:
        return [convert(value, intent)]
    return [_typed(i) for i in _split(value)]


def verified_response(
    task_type: str, value: str | Unachievable | None, failure: str | None, data: list[Item] | None
) -> dict[str, Any]:
    response: dict[str, Any] = {"task_type": task_type, "status": "SUCCESS"}
    if value is None:
        return {**response, "status": "UNKNOWN_ERROR", "error_details": failure or "no answer"}
    if isinstance(value, Unachievable) or value.strip() == UNACHIEVABLE_ANSWER:
        return {**response, "status": "NOT_FOUND_ERROR", "error_details": "not found on the site"}
    if data is not None:
        response["retrieved_data"] = data
    return response
