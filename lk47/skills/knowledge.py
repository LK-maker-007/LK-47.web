from __future__ import annotations

import re
from collections.abc import Callable

from lk47.skills.common import Precondition, Skill
from lk47.skills.shopping_admin.customers import customers
from lk47.skills.wiki import Article, Passage, article, search

COUNTRIES = {"unitedstates", "us", "usa", "unitedstatesofamerica"}
INSTITUTION = re.compile(r"\b(?:university|college|institute|school|museum|company|stadium)\b")


def place_in(value: Passage) -> str:
    parts = [p.strip() for p in value.text.split(",") if p.strip(" .") and "°" not in p]
    while parts and re.sub(r"[.\s]", "", parts[-1].lower()) in COUNTRIES:
        parts.pop()
    return ", ".join(parts[-2:])


def _article(name: str) -> Skill[Article]:
    # a title as written, then capitalised ("the big apple" is the article Big Apple), then the
    # first search result
    for title in dict.fromkeys([name, name[:1].upper() + name[1:], name.title()]):
        found = yield from article(title)
        if found is not None:
            return found
    titles = yield from search(name)
    if titles:
        found = yield from article(titles[0])
        if found is not None:
            return found
    raise Precondition(f"no article for {name!r}")


def _field(found: Article, *labels: str) -> Passage:
    value = found.field(*labels)
    if value is None:
        raise Precondition(f"no {labels[0]} in the article on {found.title}")
    return value


def _team(name: str) -> Skill[Article]:
    # "Pirates" is piracy; the team is the title that ends in the name ("Pittsburgh Pirates")
    found = yield from article(name)
    if found is not None and re.search(r"\bteam\b", found.lead.text):
        return found
    for title in (yield from search(name)):
        m = re.search(rf"((?:[A-Z][\w.]*\s)+){re.escape(name)}\b", title)
        if m:
            team = yield from article(f"{m.group(1)}{name}")
            if team is not None:
                return team
    raise Precondition(f"no team named {name!r}")


def _based(team: Article) -> str:
    m = re.search(r"\bbased in (?:the )?(.+?)(?:\.|,| and | The )", team.lead.text)
    if m is None:
        raise Precondition(f"no home city in the article on {team.title}")
    return re.sub(r"\s+metropolitan area$", "", m.group(1))


def _champion(year: str) -> Skill[str]:
    listing = yield from _article("List of Super Bowl champions")
    for table in listing.tables:
        head = [c.text for c in table[0]] if table else []
        if "Winning team" not in head or "Date/Season" not in head:
            continue
        date, winner = head.index("Date/Season"), head.index("Winning team")
        for row in table[1:]:
            if len(row) == len(head) and re.match(rf"\w+ \d+, {year}\b", row[date].text):
                links = row[winner].links
                return links[0].text if links else row[winner].text
    raise Precondition(f"no Super Bowl played in {year}")


def _customer(name: str) -> Skill[str]:
    rows = yield from customers()
    wanted = [w.lower() for w in name.split()]
    for row in rows:
        if all(w in row.name.lower() for w in wanted):
            return f"{row.zip_code}, {row.state}"
    raise Precondition(f"no customer named {name!r}")


def _located(name: str) -> Skill[str]:
    return place_in(_field((yield from _article(name)), "Location"))


def _home_city(name: str) -> Skill[str]:
    return _based((yield from _team(name)))


def _hometown(name: str) -> Skill[str]:
    return place_in(_field((yield from _article(name)), "Born"))


def _largest(name: str) -> Skill[str]:
    found = yield from _article(name)
    return f"{_field(found, 'Largest city').text}, {found.title}"


def _origin(name: str) -> Skill[str]:
    return place_in(_field((yield from _article(name)), "Region or state", "Place of origin"))


def _super_bowl(year: str) -> Skill[str]:
    return _based((yield from _team((yield from _champion(year)))))


def _city_of(name: str) -> Skill[str]:
    found = yield from article(name)
    if found is None or not INSTITUTION.search(found.lead.text.lower()):
        return name
    return place_in(_field(found, "Location"))


SHAPES: tuple[tuple[re.Pattern[str], Callable[[str], Skill[str]]], ...] = (
    (re.compile(r"city where my e-commerce customer (.+?) lives", re.I), _customer),
    (re.compile(r"^city where (?:the )?(.+?) is located$", re.I), _located),
    (re.compile(r"^home city of (?:the )?(.+)$", re.I), _home_city),
    (re.compile(r"^hometown of (.+)$", re.I), _hometown),
    (re.compile(r"^(?:biggest|largest) city (?:in|of) (.+)$", re.I), _largest),
    (re.compile(r"^city with the most authentic (.+)$", re.I), _origin),
    (re.compile(r"^home of the (\d{4}) Super Bowl champions?$", re.I), _super_bowl),
    (re.compile(r"^city of (.+)$", re.I), _city_of),
)


def city(description: str) -> Skill[str]:
    text = re.sub(r"^the\s+", "", description.strip(), flags=re.I)
    for shape, answer in SHAPES:
        if m := shape.search(text):
            return (yield from answer(m.group(1)))
    try:
        found = yield from _article(text)
    except Precondition:
        return description
    m = re.search(r"\bnickname for (.+?)\.", found.lead.text)
    return m.group(1) if m else description


def _league_arena(where: str, league: str) -> Skill[str]:
    town = yield from _article(where)
    teams = yield from _article(league)
    town_words = set(re.findall(r"\w+", town.title.lower())) - {"city"}
    for table in teams.tables:
        head = [c.text for c in table[0]] if table else []
        venue = next((h for h in head if h in ("Arena", "Stadium", "Ballpark")), "")
        if "Team" not in head or "Location" not in head or not venue:
            continue
        rows = [r for r in table[1:] if len(r) == len(head)]
        local = [r for r in rows if town.title.lower() in r[head.index("Location")].text.lower()]
        if local:
            best = max(
                local,
                key=lambda r: len(
                    town_words & set(re.findall(r"\w+", r[head.index("Team")].text.lower()))
                ),
            )
            return best[head.index(venue)].text
    raise Precondition(f"no {league} team in {town.title}")


def arena(team: str) -> Skill[str]:
    text = re.sub(r"^the\s+", "", team.strip(), flags=re.I)
    if m := re.match(r"^(.+?) (?:home )?([A-Z]{2,4}) team$", text):
        return (yield from _league_arena(m.group(1), m.group(2)))
    found = yield from _team(text)
    venue = found.field("Arena", "Ballpark", "Stadium")
    if venue is not None:
        return re.split(r"[(,]", venue.text)[0].strip()
    for passage in found.paragraphs:
        m = re.search(r"home games at (?:the )?([A-Z][\w'.&\- ]+?)(?:,|\.| in | \()", passage.text)
        if m:
            return m.group(1)
    raise Precondition(f"no home venue in the article on {found.title}")


def bordering_states(state: str) -> Skill[list[str]]:
    # the lead names the neighbours ("It borders Delaware to the southeast, ..."); a neighbour is
    # a state when its own article says when it was admitted to the Union
    found = yield from _article(state)
    passage = next((p for p in found.paragraphs[:3] if "border" in p.text), None)
    if passage is None:
        raise Precondition(f"no borders in the article on {found.title}")
    sentence = next(s for s in re.split(r"(?<=\.)\s", passage.text) if "border" in s)
    states = []
    for link in passage.links:
        if link.text not in sentence or link.text in states:
            continue
        neighbour = yield from article(link.title)
        if neighbour is not None and neighbour.field("Admitted to the Union") is not None:
            states.append(link.text)
    return states


FILMED = ("Production locations", "Production location", "Filming locations", "Filming location")


def _work(name: str, mention: str) -> Skill[Article]:
    # a title that is a disambiguation page ("The Chair may refer to:") is the listed article
    # that carries the name with a qualifier and mentions the place the task names
    found = yield from _article(name)
    if "may refer to" not in found.lead.text:
        return found
    for item in found.items:
        title = item.links[0].title if item.links else ""
        if not title.startswith(f"{name} ("):
            continue
        candidate = yield from article(title)
        if candidate is not None and any(mention in p.text for p in candidate.paragraphs):
            return candidate
    raise Precondition(f"no single article for {name!r}")


def _filmed_at(name: str) -> Skill[str]:
    found = yield from _article(name)
    for candidate in [found.title, *[link.title for link in found.lead.links[:6]]]:
        work = found if candidate == found.title else (yield from article(candidate))
        value = work.field(*FILMED) if work is not None else None
        if value is not None:
            return place_in(value)
    raise Precondition(f"no production location for {name!r}")


def _event_site(state: str, verb: str, event: str) -> Skill[str]:
    found = yield from _article(event)
    stem = verb.lower()[:5]
    for passage in found.paragraphs:
        for sentence in re.split(r"(?<=\.)\s", passage.text):
            if stem in sentence.lower() and state in sentence:
                for link in passage.links:
                    if link.text in sentence and state in link.title:
                        return link.title
    raise Precondition(f"no place in {state} for {event!r}")


def _undergraduate(concept: str) -> Skill[str]:
    found = yield from _article(concept)
    for link in found.lead.links[:5]:
        person = yield from article(link.title)
        school = person.field("Education", "Alma mater") if person is not None else None
        if school is not None and school.links:
            college = yield from article(school.links[0].title)
            return college.title if college is not None else school.links[0].text
    raise Precondition(f"no schooling for the namesake of {concept!r}")


def _colleges_filmed(work: str, place: str, besides: str) -> Skill[str]:
    found = yield from _work(work, place)
    for passage in found.paragraphs:
        for link in passage.links:
            if not re.search(r"\b(?:College|University)\b", link.title):
                continue
            after = passage.text.split(link.text, 1)[-1]
            m = re.match(r"\s+in ([A-Z][\w.&' -]+(?:, [A-Z][\w ]+)?)", after)
            town = m.group(1) if m else ""
            if besides and besides.lower() in town.lower():
                continue
            if place.lower() in town.lower() or (besides and place.lower() in passage.text.lower()):
                return link.title
    raise Precondition(f"no college named for {work!r} in {place}")


LANDMARKS: tuple[tuple[re.Pattern[str], Callable[..., Skill[str]]], ...] = (
    (re.compile(r"^place where (.+?) was filmed$", re.I), _filmed_at),
    (
        re.compile(r"^place in (.+?) where .*?\b(\w+ed)\b.*? during (?:the )?(.+)$", re.I),
        _event_site,
    ),
    (
        re.compile(r"^undergrad(?:uate)? college of the person who developed (?:the )?(.+)$", re.I),
        _undergraduate,
    ),
    (
        re.compile(
            r"^college\(?s?\)? where (.+?) was filmed in (.+?)(?: other than the ones in (.+))?$",
            re.I,
        ),
        lambda work, place, besides: _colleges_filmed(work, place, besides or ""),
    ),
)


def landmark(description: str) -> Skill[str]:
    text = re.sub(r"^the\s+", "", description.strip(), flags=re.I)
    for shape, answer in LANDMARKS:
        if m := shape.search(text):
            return (yield from answer(*m.groups()))
    titles = yield from search(text)
    if not titles:
        raise Precondition(f"nothing found for {description!r}")
    return titles[0]


def _columns(table: tuple[tuple[Passage, ...], ...]) -> tuple[list[str], int]:
    first = [c.text for c in table[0]]
    second = [c.text for c in table[1]] if len(table) > 1 else []
    if (
        second
        and second[:2] == first[:2]
        and any(a != b for a, b in zip(first, second, strict=False))
    ):
        return [a if a == b else f"{a} {b}" for a, b in zip(first, second, strict=False)], 2
    return first, 1


def _films(person: str, when: str, year: str) -> Skill[list[str]]:
    listing = yield from _article(f"{person} filmography")
    for table in listing.tables:
        head, start = _columns(table)
        director = next((i for i, h in enumerate(head) if h.endswith("Director")), -1)
        if "Title" not in head or director < 0:
            continue
        films = []
        for row in table[start:]:
            if len(row) != len(head) or row[director].text != "Yes":
                continue
            notes = row[head.index("Notes")].text.lower() if "Notes" in head else ""
            made = int(re.sub(r"\D", "", row[0].text)[:4] or 0)
            if "short" in notes or (when == "before" and made >= int(year)):
                continue
            if when == "after" and made < int(year):
                continue
            films.append(row[head.index("Title")].text)
        if films:
            return films
    raise Precondition(f"no directing credits for {person!r}")


def _accolade(person: str, award: str, outcome: str) -> Skill[list[str]]:
    found = yield from _article(person)
    for table in found.tables:
        head, start = _columns(table)
        column = f"{award} {outcome}"
        if "Title" not in head or column not in head:
            continue
        return [
            row[head.index("Title")].text
            for row in table[start:]
            if len(row) == len(head)
            and re.sub(r"\D", "", row[head.index(column)].text)
            and row[head.index("Title")].text != "Total"
        ]
    raise Precondition(f"no {award} column for {person!r}")


def _timeline(person: str) -> Skill[list[str]]:
    found = yield from _article(person)
    return [h for h in found.headings if re.match(r"^\d{4}\s*–\s*(?:\d{4}|present)", h)]


def topics(description: str) -> Skill[list[str]]:
    text = description.strip()
    if m := re.match(r"^(?:movies|films) directed by (.+?)(?: (before|after) (\d{4}))?$", text):
        return (yield from _films(m.group(1), m.group(2) or "", m.group(3) or "0"))
    if m := re.match(r"^career timeline of (.+)$", text):
        return (yield from _timeline(m.group(1)))
    if m := re.match(r"^(?:movies|films) that won (.+?) by (.+)$", text):
        return (yield from _accolade(m.group(2), m.group(1), "Wins"))
    if m := re.match(r"^(?:movies|films) that are nominated (.+?) by (.+)$", text):
        return (yield from _accolade(m.group(2), m.group(1), "Nominations"))
    raise Precondition(f"no reading for {description!r}")


def synonym(word: str) -> Skill[str | None]:
    try:
        found = yield from _article(word)
    except Precondition:
        return None
    m = re.search(r"\bsynonym for (?:an? )?([a-z][a-z ]*?)[,.]", found.lead.text)
    return m.group(1) if m else None


LOCAL = re.compile(r"\blocal (?:company|business|firm)\b", re.I)


def owner_of(chain: str) -> Skill[tuple[str, str] | None]:
    found = yield from article(chain)
    if found is None:
        return None
    parent = found.field("Parent", "Owner", "Owners")
    head = found.field("Headquarters", "Headquarters location")
    return (parent.text if parent else "", place_in(head) if head else "")
