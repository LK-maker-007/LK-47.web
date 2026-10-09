import os
from pathlib import Path

import lxml.html
import pytest

from lk47.skills.map.common import Place, kilometres, parse_results, parse_route
from lk47.skills.map.places import Query, clean, coverage, nearby, resolve, words
from lk47.skills.map.tasks import _plural, duration
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/map"


def snapshot(name: str) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", 1, lxml.html.fromstring(html))


@pytest.fixture(autouse=True)
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "MAP", "http://localhost:3000")


def place(display: str, kind: str = "", lat: float = 40.44, lon: float = -79.94) -> Place:
    return Place(display, kind, lat, lon, "node/1")


def test_search_results_carry_name_kind_and_position() -> None:
    found = parse_results(snapshot("search_starbucks_cmu.html"))
    assert found is not None and len(found) == 10
    craig = next(p for p in found if "South Craig Street" in p.display)
    assert craig.name == "Starbucks" and craig.kind == "Cafe" and craig.city == "Pittsburgh"
    assert craig.element.startswith(("node/", "way/")) and 40.4 < craig.lat < 40.5
    assert parse_results(snapshot("search_nothing.html")) == []


def test_route_summary_reads_distance_and_time() -> None:
    found = parse_route(snapshot("directions_foot.html"))
    assert found is not None and found.distance == "2.1km" and found.metres == 2100
    assert found.time == "0:29" and found.minutes == 29


def test_durations_read_as_hours_and_minutes() -> None:
    assert duration(29) == "29min" and duration(95) == "1h 35min" and duration(60) == "1h 0min"
    assert duration(0) == "less than 1min"


def test_descriptions_lose_articles_and_asides() -> None:
    assert clean("the starbuck near CMU") == "starbuck near CMU"
    assert clean("CVS (closet one)") == "CVS"
    assert clean("Gardner Steel Conference Center,") == "Gardner Steel Conference Center"


def test_coverage_counts_abbreviations_plurals_and_acronyms() -> None:
    cmu = place("Carnegie Mellon University, Schenley Drive Extension, Pittsburgh, 15213")
    assert coverage(words("CMU"), cmu, frozenset({"cmu"})) == 1.0
    assert coverage(words("Univ of Pittsburgh"), place("University of Pittsburgh, 4200")) == 1.0
    assert coverage(words("starbuck"), place("Starbucks, 417, South Craig Street")) == 1.0
    pit = frozenset({"pit"})
    assert coverage(["pit", "airport"], place("Gerrish Pit, Airport Road, Maine"), pit) == 0.5
    airport = place("Pittsburgh International Airport, Southern Beltway", "Airport")
    assert coverage(["pit", "airport"], airport, pit) == 1.0


def test_a_relation_is_resolved_through_its_anchor() -> None:
    cmu = place("Carnegie Mellon University, Pittsburgh, Allegheny County, 15213", lat=40.4442)
    near = place("Starbucks, 417, South Craig Street, Pittsburgh, Allegheny County", "Cafe", 40.445)
    far = place("Starbucks, 1400, East Carson Street, Pittsburgh, Allegheny County", "Cafe", 40.43)
    lookup = resolve("the starbuck near CMU")
    asked = [next(lookup).text]
    answers = {"CMU": [cmu], "starbucks Pittsburgh": [far, near]}
    try:
        while True:
            asked.append(lookup.send(answers.get(asked[-1], [])).text)
    except StopIteration as done:
        assert done.value == near
    assert asked[:4] == [
        "starbuck near CMU",
        "starbucks near CMU",
        "CMU",
        "starbuck near Carnegie Mellon University",
    ]


def test_a_category_search_keeps_every_result_nearest_first() -> None:
    anchor = place("Carnegie Mellon University, Pittsburgh, Allegheny County", lat=40.4442)
    sunoco = place("Sunoco, North Craig Street, Pittsburgh", "Filling Station", 40.452, -79.95)
    getgo = place("GetGo, Baum Boulevard, Pittsburgh", "Filling Station", 40.457, -79.94)
    lookup = nearby("gas station", anchor)
    assert next(lookup) == Query("gas station near Carnegie Mellon University", anchor)
    with pytest.raises(StopIteration) as done:
        lookup.send([getgo, sunoco])
    assert done.value.value == sorted([getgo, sunoco], key=lambda p: kilometres(anchor, p))


def test_search_words_are_made_plural() -> None:
    assert _plural("hotel") == "hotels" and _plural("bar") == "bars"
    assert _plural("parking") == "parking" and _plural("pharmacy") == "pharmacies"
