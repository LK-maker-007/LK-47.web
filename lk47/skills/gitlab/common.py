from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote_plus

from lk47.actions import Goto
from lk47.normalize import Unsupported, period_range
from lk47.sites import site_url
from lk47.skills.common import Postcondition, Precondition, Skill
from lk47.skills.shopping_admin.products import same_word
from lk47.snapshot import PageSnapshot

ME = "byteblaze"
FILLERS = {"the", "repo", "repository", "project", "with", "most", "stars", "of", "a", "an", "my"}


@dataclass(frozen=True)
class ProjectRow:
    path: str
    name: str
    stars: int
    description: str = ""


def base() -> str:
    return site_url("GITLAB")


def parse_projects(snapshot: PageSnapshot) -> list[ProjectRow]:
    rows = []
    for li in snapshot.css(".projects-list li.project-row"):
        link = li.cssselect("a.text-plain")
        name = li.cssselect(".project-name")
        if not link or not name:
            continue
        href = str(link[0].get("href"))
        path = href[len(base()) :] if href.startswith("http") else href
        stars = li.cssselect("a.stars")
        count = " ".join(stars[0].text_content().split()) if stars else "0"
        about = li.cssselect(".description")
        rows.append(
            ProjectRow(
                path.rstrip("/"),
                " ".join(name[0].text_content().split()),
                int(count or 0),
                " ".join(about[0].text_content().split()) if about else "",
            )
        )
    return rows


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in FILLERS]


def find_project(repo: str, others_only: bool = False) -> Skill[str]:
    # "owner/name" is a path; anything else is searched, and the row whose name shares the
    # most words with the request wins, which makes "Pytorch GAN" the PyTorch-GAN project;
    # others_only leaves out my own projects, which a fork cannot target
    text = repo.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", text):
        snapshot = yield Goto(f"{base()}/{text}")
        if "Not Found" not in (snapshot.text("title") or ""):
            return f"/{text}"
        text = text.split("/")[1]
    elif re.fullmatch(r"[\w.-]+", text):
        snapshot = yield Goto(f"{base()}/{ME}/{text}")
        if "Not Found" not in (snapshot.text("title") or ""):
            return f"/{ME}/{text}"
    words = _words(text)
    query = quote_plus(" ".join(w for w in words if not w.isdigit()) or text)
    snapshot = yield Goto(f"{base()}/search?search={query}&scope=projects")
    rows = _eligible(parse_projects(snapshot), others_only)
    described = False

    def score(row: ProjectRow) -> tuple[int, bool, bool, int]:
        about = f"{row.path} {row.description}" if described else row.name
        tokens = re.findall(r"[a-z0-9]+", about.lower())
        hits = sum(any(same_word(w, t) for t in tokens) for w in words)
        exact = row.name.lower() == text.lower()
        return hits, exact, row.path.startswith(f"/{ME}/"), row.stars

    if rows:
        return max(rows, key=score).path
    # the search is a phrase match on names; a description finds nothing as a phrase, so its
    # words are searched one at a time, longest first, until a project carries two of them
    described = True
    words = [w for w in dict.fromkeys(words) if len(w) > 2] or words
    enough = min(2, len(words))
    keys = sorted((w for w in words if not w.isdigit()), key=len, reverse=True)
    for word in keys[:4]:
        snapshot = yield Goto(f"{base()}/search?search={quote_plus(word)}&scope=projects")
        rows += _eligible(parse_projects(snapshot), others_only)
        if rows and score(max(rows, key=score))[0] >= enough:
            break
    if (not rows or score(max(rows, key=score))[0] < enough) and not others_only:
        for page in range(1, 4):
            snapshot = yield Goto(f"{base()}/dashboard/projects?page={page}")
            found = parse_projects(snapshot)
            rows += found
            if len(found) < DASHBOARD_PAGE:
                break
    if not rows or score(max(rows, key=score))[0] == 0:
        raise Precondition(f"no project found for {repo!r}")
    return max(rows, key=score).path


DASHBOARD_PAGE = 20


def _eligible(rows: list[ProjectRow], others_only: bool) -> list[ProjectRow]:
    return [r for r in rows if not r.path.startswith(f"/{ME}/")] if others_only else rows


def user_handle(name: str) -> Skill[str]:
    # the user search lists "Name @handle"; "Jakub K" is the Jakub whose surname starts with K,
    # which is not the first Jakub listed
    query = name.strip()
    snapshot = yield Goto(f"{base()}/search?search={quote_plus(query)}&scope=users")
    entries = []
    for a in snapshot.css(".search-results li a"):
        text = " ".join(a.text_content().split())
        if " @" in text:
            display, handle = text.rsplit(" @", 1)
            entries.append((display.lower().split(), handle))
    if not entries:
        raise Precondition(f"no user named {name!r}")
    wanted = query.lower().split()

    def fit(entry: tuple[list[str], str]) -> int:
        words, handle = entry
        if handle.lower() == query.lower():
            return 2
        return int(all(any(w.startswith(q) for w in words) for q in wanted))

    return max(entries, key=fit)[1]


def search_project(topic: str) -> Skill[str]:
    words = sorted(_words(topic), key=len, reverse=True)
    for query in [topic.strip(), *words[:1]]:
        snapshot = yield Goto(f"{base()}/search?search={quote_plus(query)}&scope=projects")
        rows = parse_projects(snapshot)
        if rows:
            return max(rows, key=lambda r: (not r.path.startswith(f"/{ME}/"), r.stars)).path
    raise Precondition(f"no project found for {topic!r}")


def my_projects() -> Skill[list[ProjectRow]]:
    snapshot = yield Goto(f"{base()}/dashboard/projects")
    rows = parse_projects(snapshot)
    if not rows:
        raise Postcondition("no projects on the dashboard")
    return rows


def iso(d: date) -> str:
    return d.isoformat()


def parse_due(text: str) -> date:
    s = re.sub(r"^on\s+", "", text.strip(), flags=re.I)
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    if m := re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s):
        return date(
            int(m.group(3)), period_range(f"{m.group(1)} {m.group(3)}").start.month, int(m.group(2))
        )
    if m := re.fullmatch(r"(?:the\s+)?(beginning|start|end)\s+of\s+(.+)", s, flags=re.I):
        try:
            span = period_range(m.group(2))
        except Unsupported:
            raise Precondition(f"unsupported date {text!r}") from None
        return span.end if m.group(1).lower() == "end" else span.start
    raise Precondition(f"unsupported date {text!r}")


def relative_to(start: date, text: str) -> date:
    if m := re.fullmatch(r"in\s+(\d+)\s+days?", text.strip(), flags=re.I):
        return start + timedelta(days=int(m.group(1)))
    if m := re.fullmatch(r"in\s+(\d+)\s+days?\s*\(inclusive\)", text.strip(), flags=re.I):
        return start + timedelta(days=int(m.group(1)) - 1)
    return parse_due(text)
