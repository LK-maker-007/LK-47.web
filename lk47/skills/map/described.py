from __future__ import annotations

from lk47.skills.common import REGISTRY, Precondition, Skill
from lk47.skills.knowledge import arena, bordering_states, city, landmark
from lk47.skills.map.common import Place, kilometres, route, search, show_route
from lk47.skills.map.places import coverage, locate, words
from lk47.skills.map.tasks import duration
from lk47.skills.wiki import article

PARKS = "List of national parks of the United States"
NATIONAL_PARK = "National Park"


def _city_place(description: str) -> Skill[Place]:
    name = yield from city(description)
    place = yield from locate(name)
    town = name.split(", ")[0]
    if town != name and coverage(words(name), place) < 1.0:
        # the map names no state for some towns ("Philadelphia, Philadelphia County"), and the
        # whole name finds a turnpike junction instead; the town alone finds the town
        place = yield from locate(town)
    return place


def drive_between(city1: str, city2: str) -> Skill[str]:
    a = yield from _city_place(city1)
    b = yield from _city_place(city2)
    found = yield from route(a, b, "car")
    return duration(found.minutes)


def route_between(city1: str, city2: str) -> Skill[str]:
    a = yield from _city_place(city1)
    b = yield from _city_place(city2)
    found = yield from show_route(a, b, "car")
    return duration(found.minutes)


def national_park(city_description: str, question: str) -> Skill[str]:
    origin = yield from _city_place(city_description)
    listing = yield from article(PARKS)
    if listing is None:
        raise Precondition("no list of national parks")
    parks: list[tuple[float, str]] = []
    for table in listing.tables:
        if not table or [c.text for c in table[0]][:1] != ["Name"]:
            continue
        for row in table[1:]:
            point = next((c.point for c in row if c.point), None)
            if point and row[0].links:
                spot = Place("", "", point[0], point[1], "")
                parks.append((kilometres(origin, spot), row[0].links[0].title))
    if not parks:
        raise Precondition("no parks with coordinates in the list")
    name = min(parks)[1]
    listed = yield from search(name, origin)
    park = next((p for p in listed if p.kind == NATIONAL_PARK), listed[0] if listed else None)
    if park is None:
        raise Precondition(f"{name} is not on the map")
    lowered = question.lower()
    label = park.element.split("/")[-1] if "relation id" in lowered else name
    if "drive" not in lowered and "bike" not in lowered:
        return label
    found = yield from route(origin, park, "bike" if "bike" in lowered else "car")
    if "how far" in lowered or "distance" in lowered:
        return f"{label}; {found.distance}"
    return f"{label}; {duration(found.minutes)}"


def stadium_route(location: str, sport_team: str) -> Skill[str]:
    origin = yield from locate(location)
    venue = yield from arena(sport_team)
    # the venue as the geocoder ranks it; near the start it would find namesakes in that town
    stadium = yield from locate(venue)
    found = yield from show_route(origin, stadium, "car")
    return duration(found.minutes)


def borders(state: str) -> Skill[str]:
    states = yield from bordering_states(state)
    if not states:
        return "N/A"
    return ", ".join(states)


def border_relations(state: str) -> Skill[str]:
    states = yield from bordering_states(state)
    ids = []
    for name in states:
        listed = yield from search(name)
        match = next(
            (p for p in listed if p.name == name and p.element.startswith("relation/")), None
        )
        if match is not None:
            ids.append(match.element.split("/")[-1])
    return ", ".join(ids) if ids else "N/A"


def find_page(description: str) -> Skill[str]:
    name = yield from landmark(description)
    place = yield from locate(name)
    yield from search(place.display, place)
    return ""


REGISTRY["map.drive_between"] = drive_between
REGISTRY["map.route_between"] = route_between
REGISTRY["map.national_park"] = national_park
REGISTRY["map.stadium_route"] = stadium_route
REGISTRY["map.borders"] = borders
REGISTRY["map.border_relations"] = border_relations
REGISTRY["map.find_page"] = find_page
