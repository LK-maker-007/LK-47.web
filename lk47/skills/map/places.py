from __future__ import annotations

import difflib
import functools
import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from lk47.skills.common import Precondition, Skill
from lk47.skills.map.common import Place, kilometres, search

T = TypeVar("T")


@dataclass(frozen=True)
class Query:
    text: str
    near: Place | None = None


Lookup = Generator[Query, list[Place], "Place | None"]
Nearby = Generator[Query, list[Place], list[Place]]

RELATION = re.compile(r"^(.+?)\s+(?:near|around|at|on|in|by|close to|next to)\s+(.+)$", re.I)
ACRONYM = re.compile(r"^[A-Z]{2,5}$")
ARTICLES = ("the ", "a ", "an ")
FILLER = {"a", "an", "the", "of", "in", "at", "on", "near", "around", "by", "to", "close", "next"}
ENOUGH = 0.5
LOCAL_KM = 30.0
NEARBY_KM = 40.0


def clean(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text)
    text = " ".join(text.split()).strip(" ,.")
    for article in ARTICLES:
        if text.lower().startswith(article):
            return text[len(article) :]
    return text


DICTIONARY = Path("/usr/share/dict/words")
CLOSE = 0.8


@functools.cache
def _vocabulary() -> frozenset[str]:
    if not DICTIONARY.exists():
        return frozenset()
    return frozenset(w.strip().lower() for w in DICTIONARY.read_text().split() if "'" not in w)


def respell(text: str) -> str:
    # intents carry typos ("resturants", "Pittsburhg"); a lower-case or capitalised word the
    # dictionary lacks becomes its closest entry, keeping its capital
    vocabulary = _vocabulary()

    def fix(m: re.Match[str]) -> str:
        word = m.group(0)
        if len(word) < 5 or word.isupper() or word.lower() in vocabulary:
            return word
        close = difflib.get_close_matches(word.lower(), vocabulary, n=1, cutoff=CLOSE)
        if not close:
            return word
        return close[0].capitalize() if word[0].isupper() else close[0]

    return re.sub(r"[A-Za-z]+", fix, text)


def respellings(word: str) -> list[str]:
    if word.lower() in _vocabulary():
        return []
    return difflib.get_close_matches(word.lower(), _vocabulary(), n=3, cutoff=CLOSE)


def words(text: str) -> list[str]:
    found = re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))
    return [w for w in dict.fromkeys(found) if w not in FILLER]


def acronyms(text: str) -> frozenset[str]:
    return frozenset(t.lower() for t in re.findall(r"[A-Za-z]+", text) if ACRONYM.match(t))


def _same(word: str, token: str) -> bool:
    if word == token:
        return True
    if len(word) >= 3 and token.startswith(word):
        return True
    return len(token) >= 4 and word.startswith(token) and len(word) - len(token) <= 2


def _initials(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w[0].isupper()).lower()


def coverage(wanted: list[str], place: Place, short: frozenset[str] = frozenset()) -> float:
    # the share of the words asked for that the place's name, address or kind carries; an
    # acronym is carried by the name's initials in any order ("NYC", City of New York), by
    # itself in capitals, or by a longer word it begins ("PIT", Pittsburgh)
    if not wanted:
        return 0.0
    tokens = words(f"{place.display} {place.kind}")
    hits = 0
    for w in wanted:
        if w in short:
            hits += (
                sorted(w) == sorted(_initials(place.name))
                or re.search(rf"\b{w.upper()}\b", place.display) is not None
                or any(t.startswith(w) and len(t) > len(w) for t in tokens)
            )
        else:
            hits += any(_same(w, t) for t in tokens)
    return hits / len(wanted)


def _rank(
    places: list[Place], wanted: list[str], short: frozenset[str], around: Place | None
) -> list[Place]:
    def key(item: tuple[int, Place]) -> tuple[float, float]:
        order, place = item
        far = kilometres(place, around) if around is not None else float(order)
        return (-coverage(wanted, place, short), far)

    unique = {p.element: p for p in places}
    return [p for _, p in sorted(enumerate(unique.values()), key=key)]


def _shorter(thing: str) -> list[str]:
    tokens = thing.split()
    if len(tokens) < 2:
        return []
    out = [" ".join(tokens[:k]) for k in range(len(tokens) - 1, 0, -1)]
    out += [" ".join(tokens[:i] + tokens[i + 1 :]) for i in range(1, len(tokens) - 1)]
    return list(dict.fromkeys(out))


SHORTER_TRIES = 5


def _plural(thing: str) -> str:
    return thing[:-1] if thing.endswith("s") else thing + "s"


def nearby(thing: str, anchor: Place) -> Nearby:
    # places of a kind or a name around an anchor, best match first and nearest among equals;
    # the geocoder reads "cafe near X" as a category search, and a name it does not know as a
    # category is found by name within the anchor's town
    wanted, short = words(thing), acronyms(thing)
    around = yield Query(f"{thing} near {anchor.name}", anchor)
    if around and len({p.kind for p in around}) == 1:
        return sorted(around, key=lambda p: kilometres(p, anchor))
    head = thing.rsplit(maxsplit=1)[-1]
    if head != thing and head.lower() not in FILLER:
        kind = yield Query(f"{head} near {anchor.name}", anchor)
        if kind and len({p.kind for p in kind}) == 1:
            around += kind
    named = _rank(
        [p for p in around if coverage(wanted, p, short) >= ENOUGH], wanted, short, anchor
    )
    full = [p for p in named if coverage(wanted, p, short) == 1.0]
    if full:
        return full
    for text in [thing, _plural(thing), *_shorter(thing)][: SHORTER_TRIES + 2]:
        places = yield Query(f"{text} {anchor.city}", anchor)
        local = [
            p
            for p in places
            if coverage(words(text), p, short) >= ENOUGH and kilometres(p, anchor) <= NEARBY_KM
        ]
        if local:
            return _rank(local + named, wanted, short, anchor)
    return named or _rank(around, wanted, short, anchor)


def _splits(text: str) -> list[tuple[str, str]]:
    tokens = text.split()
    if len(tokens) < 2:
        return []
    out = []
    for i, token in enumerate(tokens):
        if ACRONYM.match(token):
            out.append((" ".join(tokens[:i] + tokens[i + 1 :]), token))
    if len(tokens) >= 3 and tokens[-1].lower() not in FILLER:
        out.append((tokens[-1], " ".join(tokens[:-1])))
    return out


DEPTH = 2
ANY_KM = 0.5


def resolve(description: str, context: Place | None = None, depth: int = 0) -> Lookup:
    text = clean(description)
    seen: list[Place] = yield Query(text, context)
    if not seen and respell(text) != text:
        respelled = yield Query(respell(text), context)
        if respelled:
            text, seen = respell(text), respelled
    wanted, short = words(text), acronyms(text)
    head = text.split(", ")[0].lower()
    named = [p for p in seen if ", " in text and p.name.lower() == head]
    first = named[0] if named else seen[0] if seen else None
    local = context is None or (first is not None and kilometres(first, context) <= LOCAL_KM)
    if first is not None and local and (named or coverage(wanted, first, short) == 1.0):
        return first
    if context is not None and context.city and context.city.lower() not in text.lower():
        seen += yield Query(f"{text} {context.city}", context)
    ranked = _rank(seen, wanted, short, context)
    if ranked and coverage(wanted, ranked[0], short) == 1.0:
        # when nothing that fits lies near the context, the context says nothing and the site's
        # order holds ("NYC" from Pittsburgh is the city, not a railway named NYC)
        far = context is not None and kilometres(ranked[0], context) > LOCAL_KM
        return next(p for p in seen if coverage(wanted, p, short) == 1.0) if far else ranked[0]
    m = RELATION.match(text)
    pairs = [(m.group(1), m.group(2))] if m is not None else _splits(text)
    for thing, where in pairs if depth < DEPTH else []:
        anchor = yield from resolve(where, context, depth + 1)
        if anchor is None:
            continue
        found = yield from nearby(clean(thing), anchor)
        if found and context is not None and description.lower().startswith(("a ", "an ")):
            same = [p for p in found if coverage(words(thing), p) >= ENOUGH]
            close = [p for p in same or found if kilometres(p, anchor) <= ANY_KM]
            return min(close or found, key=lambda p: kilometres(p, context))
        if found:
            return found[0]
    if ranked and coverage(wanted, ranked[0], short) >= ENOUGH:
        return ranked[0]
    return None


def resolve_pair(first: str, second: str) -> Generator[Query, list[Place], tuple[Place, Place]]:
    swap = _related(first) and not _related(second)
    if swap:
        first, second = second, first
    a = yield from resolve(first)
    if a is None:
        raise Precondition(f"no place found for {first!r}")
    b = yield from resolve(second, a)
    if b is None:
        raise Precondition(f"no place found for {second!r}")
    if kilometres(a, b) > LOCAL_KM:
        again = yield from resolve(first, b)
        if again is not None and kilometres(again, b) < kilometres(a, b):
            a = again
    return (b, a) if swap else (a, b)


def _related(description: str) -> bool:
    return RELATION.match(clean(description)) is not None


def drive(lookup: Generator[Query, list[Place], T]) -> Skill[T]:
    try:
        query = next(lookup)
        while True:
            places = yield from search(query.text, query.near)
            query = lookup.send(places)
    except StopIteration as done:
        value: T = done.value
        return value


def locate(description: str, context: Place | None = None) -> Skill[Place]:
    found = yield from drive(resolve(description, context))
    if found is None:
        raise Precondition(f"no place found for {description!r}")
    return found


def locate_pair(first: str, second: str) -> Skill[tuple[Place, Place]]:
    return (yield from drive(resolve_pair(first, second)))


def around(thing: str, anchor: Place) -> Skill[list[Place]]:
    return (yield from drive(nearby(thing, anchor)))
