from __future__ import annotations

import re

from lk47.skills.common import Precondition, Skill
from lk47.skills.knowledge import LOCAL, owner_of, synonym
from lk47.skills.map.common import Place, kilometres, search
from lk47.skills.map.places import around, locate, respellings

OWNED = re.compile(r"^(.+?)\s+own(?:ed)?\s+by\s+(.+)$", re.I)
# a company is local when its headquarters lie this close to the place the task is about
LOCAL_KM = 60.0


def _kinds(kind: str) -> list[str]:
    head = kind.rsplit(maxsplit=1)[-1]
    return [head, *respellings(head)]


def places_of(thing: str, anchor: Place) -> Skill[list[Place]]:
    m = OWNED.match(thing.strip())
    kind, owner = (m.group(1), m.group(2)) if m else (thing, "")
    found = yield from around(kind, anchor)
    for word in _kinds(kind) if not found else []:
        listed = yield from search(f"{word} near {anchor.name}", anchor)
        if not listed:
            same = yield from synonym(word)
            listed = (yield from search(f"{same} near {anchor.name}", anchor)) if same else []
        if listed:
            found = sorted(listed, key=lambda p: kilometres(p, anchor))
            break
    if not owner:
        return found
    owned = []
    checked: dict[str, bool] = {}
    for place in found:
        if place.name not in checked:
            checked[place.name] = yield from _owned_by(place.name, owner, anchor)
        if checked[place.name]:
            owned.append(place)
    if not owned:
        raise Precondition(f"no {kind!r} owned by {owner!r} near {anchor.name}")
    return owned


def _owned_by(chain: str, owner: str, anchor: Place) -> Skill[bool]:
    known = yield from owner_of(chain)
    if known is None:
        return False
    parent, headquarters = known
    if not LOCAL.search(owner):
        return owner.lower() in parent.lower()
    if not headquarters:
        return False
    try:
        home = yield from locate(headquarters)
    except Precondition:
        return False
    return kilometres(home, anchor) <= LOCAL_KM
