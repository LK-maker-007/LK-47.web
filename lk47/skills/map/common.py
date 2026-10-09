from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from urllib.parse import quote

from lk47.actions import Goto
from lk47.sites import site_url
from lk47.skills.common import Postcondition, Precondition, Skill, settle
from lk47.snapshot import PageSnapshot

ENGINES = {"car": "fossgis_osrm_car", "bike": "fossgis_osrm_bike", "foot": "fossgis_osrm_foot"}
# the search favours what the map shows; this zoom shows a neighbourhood about 2 km across
NEIGHBOURHOOD_ZOOM = 16
SEARCH_WAITS = 6
ROUTE_WAITS = 10
SUMMARY = re.compile(r"Distance: ([\d.,]+)(m|km)\. Time: (\d+):(\d\d)\.")


@dataclass(frozen=True)
class Place:
    display: str
    kind: str
    lat: float
    lon: float
    element: str

    @property
    def name(self) -> str:
        return self.display.split(", ")[0]

    @property
    def address(self) -> str:
        return self.display.split(", ", 1)[1] if ", " in self.display else ""

    @property
    def city(self) -> str:
        parts = self.display.split(", ")
        for i, part in enumerate(parts):
            if part.endswith(" County") and i > 1:
                return parts[i - 1]
        return parts[-3] if len(parts) >= 3 else ""


@dataclass(frozen=True)
class Route:
    metres: float
    minutes: int
    distance: str
    time: str


def base() -> str:
    return site_url("MAP")


def kilometres(a: Place, b: Place) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def parse_results(snapshot: PageSnapshot) -> list[Place] | None:
    places = []
    for a in snapshot.css("#sidebar_content a.set_position"):
        places.append(
            Place(
                a.get("data-name") or "",
                a.get("data-prefix") or "",
                float(a.get("data-lat") or 0),
                float(a.get("data-lon") or 0),
                (a.get("href") or "").lstrip("/"),
            )
        )
    if places:
        return places
    panel = snapshot.text("#sidebar_content") or ""
    if "No results found" in panel:
        return []
    return None


def search(query: str, near: Place | None = None) -> Skill[list[Place]]:
    url = f"{base()}/search?query={quote(query)}"
    if near is not None:
        url += f"#map={NEIGHBOURHOOD_ZOOM}/{near.lat:.5f}/{near.lon:.5f}"
    snapshot = yield Goto(url)
    for n in range(SEARCH_WAITS):
        places = parse_results(snapshot)
        if places is not None:
            return places
        snapshot = yield settle(n)
    raise Postcondition(f"no search results shown for {query!r}")


def parse_route(snapshot: PageSnapshot) -> Route | None:
    m = SUMMARY.search(snapshot.text("#sidebar_content") or "")
    if m is None:
        return None
    number, unit, hours, minutes = m.groups()
    metres = float(number.replace(",", "")) * (1000 if unit == "km" else 1)
    return Route(metres, int(hours) * 60 + int(minutes), number + unit, f"{hours}:{minutes}")


def _directions(url: str) -> Skill[Route]:
    snapshot = yield Goto(url)
    for n in range(ROUTE_WAITS):
        found = parse_route(snapshot)
        if found is not None:
            return found
        if "find a route" in (snapshot.text("#sidebar_content") or ""):
            raise Precondition("the router found no route")
        snapshot = yield settle(n)
    raise Postcondition("no route summary shown")


def route(a: Place, b: Place, mode: str) -> Skill[Route]:
    ends = quote(f"{a.lat:.6f},{a.lon:.6f};{b.lat:.6f},{b.lon:.6f}")
    return (yield from _directions(f"{base()}/directions?engine={ENGINES[mode]}&route={ends}"))


def show_route(a: Place, b: Place, mode: str) -> Skill[Route]:
    url = (
        f"{base()}/directions?engine={ENGINES[mode]}&from={quote(a.display)}&to={quote(b.display)}"
    )
    return (yield from _directions(url))


def tags(place: Place) -> Skill[dict[str, str]]:
    # the website's own element pages are empty in this image; the geocoder that serves the
    # same map keeps every tag of a place
    kind, ident = place.element.split("/")
    snapshot = yield Goto(
        f"{base()}/nominatim/details.php?osmtype={kind[0].upper()}&osmid={ident}&format=json"
    )
    try:
        record = json.loads(snapshot.text("pre") or snapshot.text("body") or "")
    except json.JSONDecodeError:
        raise Postcondition(f"no details for {place.element}") from None
    found: dict[str, str] = {}
    for group in ("names", "addresstags", "extratags"):
        found.update(record.get(group) or {})
    return found
