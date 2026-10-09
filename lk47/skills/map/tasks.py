from __future__ import annotations

import ast
import itertools
import re
from urllib.parse import quote

from lk47.actions import Goto
from lk47.skills.common import REGISTRY, Precondition, Skill
from lk47.skills.map.common import Place, Route, base, kilometres, route, search, show_route, tags
from lk47.skills.map.owned import places_of
from lk47.skills.map.places import ANY_KM, around, clean, locate, locate_pair, respell

# walking covers about 80 m a minute on the router's foot profile; a place further than this many
# kilometres in a straight line per minute allowed cannot be reached in time
WALK_KM_PER_MIN = 0.08
CANDIDATES = 3
POSTCODE = re.compile(r"\b\d{5}\b")


def duration(minutes: int) -> str:
    if minutes == 0:
        return "less than 1min"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest}min" if hours else f"{rest}min"


def _mode(text: str) -> str:
    lowered = text.lower()
    if "walk" in lowered or "foot" in lowered:
        return "foot"
    if "bik" in lowered or "cycl" in lowered:
        return "bike"
    return "car"


def _nearest_by(
    origin: Place, places: list[Place], mode: str, metric: str = "metres", count: int = CANDIDATES
) -> Skill[tuple[Place, Route]]:
    best: tuple[Place, Route] | None = None
    for place in sorted(places, key=lambda p: kilometres(origin, p))[:count]:
        found = yield from route(origin, place, mode)
        if best is None or getattr(found, metric) < getattr(best[1], metric):
            best = (place, found)
    if best is None:
        raise Precondition("no candidate to measure")
    return best


INDEFINITE = re.compile(r"^an?\s+(.+?)\s+(?:at|in|on|near)\s+(.+)$", re.I)


def walk_time(start: str, end: str) -> Skill[str]:
    a, b = yield from locate_pair(start, end)
    m = INDEFINITE.match(end.strip())
    if m is None:
        found = yield from route(a, b, "foot")
        return duration(found.minutes)
    anchor = yield from locate(m.group(2))
    listed = yield from around(m.group(1), anchor)
    near = [p for p in listed if kilometres(p, anchor) <= ANY_KM]
    _, found = yield from _nearest_by(a, near or [b], "foot", "minutes")
    return duration(found.minutes)


def drive_time(start: str, end: str) -> Skill[str]:
    a, b = yield from locate_pair(start, end)
    found = yield from route(a, b, "car")
    return duration(found.minutes)


NEAREST_ONE = re.compile(r"\((?:closest|closet|nearest) one\)", re.I)


def walk_distance(start: str, end: str) -> Skill[str]:
    if NEAREST_ONE.search(start):
        start, end = end, start
    if not NEAREST_ONE.search(end):
        a, b = yield from locate_pair(start, end)
        found = yield from route(a, b, "foot")
        return found.distance
    origin = yield from locate(start)
    branches = yield from around(clean(end), origin)
    if not branches:
        raise Precondition(f"no {clean(end)!r} near {start!r}")
    _, found = yield from _nearest_by(origin, branches, "foot", count=2 * CANDIDATES)
    return found.distance


def compare_times(start: str, end: str) -> Skill[str]:
    a, b = yield from locate_pair(start, end)
    car = yield from route(a, b, "car")
    foot = yield from route(a, b, "foot")
    return f"driving: {duration(car.minutes)}, walking: {duration(foot.minutes)}"


def walk_then_drive(first: str, second: str, third: str) -> Skill[str]:
    a, b = yield from locate_pair(first, second)
    c = yield from locate(third, b)
    walk = yield from route(a, b, "foot")
    drive = yield from route(b, c, "car")
    return f"{walk.minutes + drive.minutes} min"


def reachable_in_hour(place: str, location: str, town: str) -> Skill[str]:
    where = yield from locate(town)
    target = yield from locate(f"{place} in {town}")
    origin = yield from locate(location, where)
    found = yield from route(origin, target, "car")
    return "Yes" if found.minutes <= 60 else "No"


def zip_code(place: str) -> Skill[str]:
    found = yield from locate(place)
    codes = POSTCODE.findall(found.display)
    if not codes:
        raise Precondition(f"no postcode in {found.display!r}")
    return str(codes[-1])


def coordinates(location: str) -> Skill[str]:
    found = yield from locate(location)
    return f"{found.lat}, {found.lon}"


INFORMATION = {
    "phone": "phone",
    "operator": "operator",
    "website": "website",
    "hours": "opening_hours",
    "opening": "opening_hours",
}


def information(information: str, location: str) -> Skill[str]:
    found = yield from locate(location)
    record = yield from tags(found)
    key = next((tag for word, tag in INFORMATION.items() if word in information.lower()), "")
    value = record.get(key) or record.get(f"contact:{key}") or ""
    if not value:
        return "N/A"
    if key == "phone":
        digits = re.sub(r"\D", "", value.split(";")[0])
        return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
    return value


def description_page(location: str) -> Skill[str]:
    # the website keeps no element pages in this image; the search result for the place's
    # full name is the page that describes it
    found = yield from locate(location)
    yield from search(found.display, found)
    return ""


def _plural(noun: str) -> str:
    if noun.endswith(("ing", "s")):
        return noun
    if noun.endswith("y") and noun[-2:-1] not in "aeiou":
        return noun[:-1] + "ies"
    return noun + "s"


def search_around(space: str, location: str) -> Skill[str]:
    query = f"{_plural(respell(space))} near {clean(location)}"
    yield Goto(f"{base()}/search?query={quote(query)}")
    return ""


def show_directions(start: str, end: str, transportation: str) -> Skill[str]:
    a, b = yield from locate_pair(start, end)
    yield from show_route(a, b, _mode(transportation))
    return ""


def walkway_to_closest(store: str, location: str) -> Skill[str]:
    origin = yield from locate(location)
    stores = yield from places_of(store, origin)
    if not stores:
        raise Precondition(f"no {store!r} near {location!r}")
    nearest, _ = yield from _nearest_by(origin, stores, "foot")
    yield from show_route(origin, nearest, "foot")
    return ""


def _origin(start: str, thing: str) -> Skill[Place | None]:
    try:
        return (yield from locate(start))
    except Precondition:
        listed = yield from search(clean(thing))
        if listed:
            raise
        return None


def nearest_with_walk(places: str, start: str) -> Skill[str]:
    origin = yield from _origin(start, places)
    if origin is None:
        return "N/A"
    found = yield from around(places, origin)
    if not found:
        return "N/A"
    nearest, walk = yield from _nearest_by(origin, found, "foot")
    return f"{nearest.display}; walking distance {walk.distance}"


def nearest_where(location: str, location2: str, condition: str) -> Skill[str]:
    origin = yield from locate(location2)
    found = yield from around(location, origin)
    if not found:
        return "N/A"
    limit = re.search(r"(\d+)\s*min", condition)
    nearest, walk = yield from _nearest_by(origin, found, _mode(condition) if limit else "car")
    if limit and walk.minutes > int(limit.group(1)):
        return "N/A"
    return nearest.display


# the map files fast-food places apart from restaurants; a person asking for restaurants counts them
ALSO = {"restaurant": "fast food"}


def closest(place1: str, place2: str) -> Skill[str]:
    anchor = yield from locate(place2)
    found = yield from around(place1, anchor)
    if not found:
        return "N/A"
    nearest = min(found, key=lambda p: kilometres(anchor, p))
    if place1.lower() in ALSO:
        found += yield from around(ALSO[place1.lower()], anchor)
    same = [p.name for p in found if p.address == nearest.address]
    return ", ".join(dict.fromkeys(same))


def nearest_by_modes(location: str, start: str, modes: str) -> Skill[str]:
    origin = yield from locate(start)
    found = yield from around(location, origin)
    if not found:
        return "N/A"
    chosen = [m for m in ("foot", "car", "bike") if m in modes.split()] or ["foot", "car", "bike"]
    nearest, _ = yield from _nearest_by(origin, found, chosen[0])
    times = []
    for mode in chosen:
        found_route = yield from route(origin, nearest, mode)
        times.append(f"{_LABEL[mode]}: {duration(found_route.minutes)}")
    return f"{nearest.name}; " + ", ".join(times)


_LABEL = {"foot": "Walk", "car": "Drive", "bike": "Bike"}


def hotels_within_walk(location: str, n: str) -> Skill[str]:
    anchor = yield from locate(location)
    hotels = yield from around("hotel", anchor)
    minutes = int(n)
    found = []
    for hotel in sorted(hotels, key=lambda p: kilometres(anchor, p)):
        if kilometres(anchor, hotel) > minutes * WALK_KM_PER_MIN:
            break
        walk = yield from route(hotel, anchor, "foot")
        if walk.minutes <= minutes:
            found.append(f"{hotel.name}: {walk.distance}")
    return "; ".join(found) or "N/A"


def best_order(place_list: str) -> Skill[str]:
    names = [str(n) for n in ast.literal_eval(place_list)]
    first = yield from locate(names[0])
    places = [first]
    for name in names[1:]:
        found = yield from locate(name, first)
        places.append(found)
    minutes: dict[tuple[int, int], int] = {}
    totals: dict[tuple[int, ...], int] = {}
    for order in itertools.permutations(range(1, len(places))):
        path = (0, *order)
        for i, j in itertools.pairwise(path):
            if (i, j) not in minutes:
                leg = yield from route(places[i], places[j], "car")
                minutes[(i, j)] = leg.minutes
        totals[path] = sum(minutes[leg] for leg in itertools.pairwise(path))
    best = min(totals, key=lambda path: totals[path])
    return "The order is " + ", ".join(names[i] for i in best)


AIRPORT = "Aerodrome"


def airports_within(airport_type: str, radius: str, start: str) -> Skill[str]:
    # airports are few and far apart, so they are listed by the county and the state of the start
    # rather than around it
    origin = yield from locate(start)
    limit = float(re.sub(r"[^\d.]", "", radius))
    kinds = clean(airport_type).removeprefix("US ").rstrip("s")
    parts = origin.display.split(", ")
    counties = [i for i, part in enumerate(parts) if part.endswith(" County")]
    regions = [parts[i] for i in counties[:1]]
    if counties and counties[0] + 1 < len(parts) and not parts[counties[0] + 1][0].isdigit():
        regions.append(parts[counties[0] + 1])
    found: dict[str, Place] = {}
    for region in regions or [origin.city]:
        listed = yield from search(f"{kinds} {region}", origin)
        for place in listed:
            if place.kind == AIRPORT and kilometres(origin, place) <= limit:
                found[place.element] = place
    within = []
    for place in sorted(found.values(), key=lambda p: kilometres(origin, p)):
        if "international" in kinds.lower() and "International" not in place.name:
            continue
        drive = yield from route(origin, place, "car")
        if drive.metres <= limit * 1000:
            within.append(place.display)
    if not within:
        return f"There is no {kinds} within {radius} of {start}"
    return "; ".join(within)


def hotel_and_supermarket(place: str, target1: str, information: str, target2: str) -> Skill[str]:
    origin = yield from locate(place)
    hotels = yield from around(target1, origin)
    if not hotels:
        return "N/A"
    hotel = hotels[0]
    shops = yield from places_of(clean(target2).removeprefix("nearest "), hotel)
    if not shops:
        return f"{hotel.name}; N/A"
    mode = _mode(information)
    metric = "minutes" if "time" in information.lower() else "metres"
    _, best = yield from _nearest_by(hotel, shops, mode, metric)
    value = duration(best.minutes) if metric == "minutes" else best.distance
    return f"{hotel.name}; {value}"


def chain_walk(start: str, first: str, second: str) -> Skill[str]:
    origin = yield from locate(start)
    stops = yield from around(first, origin)
    if not stops:
        return "N/A"
    stop = stops[0]
    ends = yield from around(second, stop)
    if not ends:
        return f"{stop.display}; N/A"
    end, walk = yield from _nearest_by(stop, ends, "foot")
    return f"{stop.display}; {end.name}, walking distance {walk.distance}"


def hotel_and_shops_within(
    place: str, target1: str, target2: str, minutes: str, mode: str
) -> Skill[str]:
    origin = yield from locate(place)
    hotels = yield from around(target1, origin)
    if not hotels:
        return "N/A"
    hotel = hotels[0]
    shops = yield from around(target2, hotel)
    within = []
    for shop in sorted(shops, key=lambda p: kilometres(hotel, p)):
        trip = yield from route(hotel, shop, _mode(mode))
        if trip.minutes <= int(minutes):
            within.append(shop.name)
    return f"{hotel.name}; " + (", ".join(dict.fromkeys(within)) or "none")


REGISTRY["map.walk_time"] = walk_time
REGISTRY["map.drive_time"] = drive_time
REGISTRY["map.walk_distance"] = walk_distance
REGISTRY["map.compare_times"] = compare_times
REGISTRY["map.walk_then_drive"] = walk_then_drive
REGISTRY["map.reachable_in_hour"] = reachable_in_hour
REGISTRY["map.zip_code"] = zip_code
REGISTRY["map.coordinates"] = coordinates
REGISTRY["map.information"] = information
REGISTRY["map.description_page"] = description_page
REGISTRY["map.search_around"] = search_around
REGISTRY["map.show_directions"] = show_directions
REGISTRY["map.walkway_to_closest"] = walkway_to_closest
REGISTRY["map.nearest_with_walk"] = nearest_with_walk
REGISTRY["map.nearest_where"] = nearest_where
REGISTRY["map.closest"] = closest
REGISTRY["map.nearest_by_modes"] = nearest_by_modes
REGISTRY["map.hotels_within_walk"] = hotels_within_walk
REGISTRY["map.best_order"] = best_order
REGISTRY["map.airports_within"] = airports_within
REGISTRY["map.hotel_and_supermarket"] = hotel_and_supermarket
REGISTRY["map.chain_walk"] = chain_walk
REGISTRY["map.hotel_and_shops_within"] = hotel_and_shops_within
