from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote, quote_plus

from lk47.actions import Click, Goto, Hover, Locator
from lk47.normalize import Unsupported, period_range
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill, settle
from lk47.skills.gitlab.common import (
    ME,
    base,
    find_project,
    my_projects,
    parse_due,
    parse_projects,
    user_handle,
)
from lk47.skills.shopping_admin.products import same_word
from lk47.snapshot import PageSnapshot

NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass(frozen=True)
class Contributor:
    name: str
    commits: int
    email: str


def todos() -> Skill[str]:
    yield Goto(f"{base()}/dashboard/todos")
    return ""


def merge_requests_assigned() -> Skill[str]:
    yield Goto(f"{base()}/dashboard/merge_requests?assignee_username={ME}")
    return ""


def merge_requests_to_review() -> Skill[str]:
    yield Goto(f"{base()}/dashboard/merge_requests?reviewer_username={ME}")
    return ""


def explore() -> Skill[str]:
    yield Goto(f"{base()}/explore")
    return ""


def recent_open_issues() -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    yield Goto(f"{base()}{project}/-/issues/?sort=created_date&state=opened")
    return ""


def _project_of(url: str) -> str:
    m = re.match(r"https?://[^/]+(/[^/]+/[^/]+)", url)
    if m is None:
        raise Precondition(f"not inside a project: {url}")
    return m.group(1)


def labels_of(project: str, wanted: str = "") -> Skill[list[str]]:
    words = re.findall(r"[a-z0-9]+", wanted.lower())
    stem = words[0] if words else ""
    if len(stem) > 3 and stem.endswith("s"):
        stem = stem[:-1]
    query = f"?search={quote_plus(stem)}" if stem else ""
    snapshot = yield Goto(f"{base()}{project}/-/labels{query}")
    names = [
        " ".join(e.text_content().split()) for e in snapshot.css(".label-name, .gl-label-text")
    ]
    return list(dict.fromkeys(n for n in names if n))


def resolve_label(names: list[str], wanted: str) -> str:
    words = re.findall(r"[a-z0-9]+", wanted.lower())
    best: tuple[int, str] | None = None
    for name in names:
        tokens = re.findall(r"[a-z0-9]+", name.lower())
        hits = sum(any(same_word(w, t) for t in tokens) for w in words)
        if hits and (best is None or hits > best[0]):
            best = (hits, name)
    if best is None:
        raise Precondition(f"no label like {wanted!r}")
    return best[1]


def issues_by_label(repo: str, label: str) -> Skill[str]:
    project = yield from find_project(repo)
    names = yield from labels_of(project, label)
    chosen = resolve_label(names, label)
    yield Goto(f"{base()}{project}/-/issues/?label_name%5B%5D={quote(chosen, safe='')}")
    return ""


ISSUE_FILLERS = {"that", "report", "ask", "about", "related", "requesting", "new", "all", "the"}
LABEL_SYNONYMS = {"feature": ("enhancement",), "features": ("enhancement",)}


def open_issues_about(description: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    issues = f"{base()}{project}/-/issues/?"
    unlabelled = r"(?:don't|do not|without|no)\s+(?:have\s+)?(?:any\s+)?labels?"
    if re.search(unlabelled, description, re.I):
        yield Goto(f"{issues}label_name%5B%5D=None")
        return ""
    tokens = description.split()
    search = [t.strip(",.") for t in tokens if len(t) > 1 and t.strip(",.").isupper()]
    words = [w for w in re.findall(r"[a-z0-9]+", description.lower()) if w not in ISSUE_FILLERS]
    words = [w for w in words if w.upper() not in search]
    candidates = words + [syn for w in words for syn in LABEL_SYNONYMS.get(w, ())]
    chosen = None
    for word in candidates:
        names = yield from labels_of(project, word)
        if names:
            chosen = resolve_label(names, word)
            break
    if chosen is None:
        raise Precondition(f"no label like {description!r}")
    query = f"search={quote_plus(' '.join(search))}&" if search else ""
    yield Goto(f"{issues}{query}label_name%5B%5D={quote(chosen, safe='')}")
    return ""


def clone_command(repo: str) -> Skill[str]:
    project = yield from find_project(repo)
    snapshot = yield Goto(f"{base()}{project}")
    ssh = snapshot.value("input#ssh_project_clone")
    if not ssh:
        raise Postcondition(f"no SSH clone address on {project}")
    return f"git clone {ssh}"


def _commit_rows(snapshot: PageSnapshot) -> list[tuple[date, str]]:
    rows = []
    day: date | None = None
    for li in snapshot.css("li.commit-header, li.commit"):
        if "commit-header" in str(li.get("class", "")):
            day = date.fromisoformat(str(li.get("data-day")))
            continue
        author = li.cssselect("a.commit-author-link")
        if day and author:
            rows.append((day, " ".join(author[0].text_content().split())))
    return rows


def _same_person(author: str, wanted: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", author.lower())

    def alike(a: str, b: str) -> bool:
        short, long = sorted((a, b), key=len)
        return a == b or (len(short) >= 5 and long.startswith(short))

    return all(any(alike(w, t) for t in tokens) for w in re.findall(r"[a-z0-9]+", wanted.lower()))


def _commits_by(project: str, user: str, until: date | None) -> Skill[list[date]]:
    # the author filter is a substring match, so the first five letters of the first name find
    # the short forms too and the rows are then kept by name; pages are 40 commits
    query = quote_plus(user.split(maxsplit=1)[0][:5])
    days: list[date] = []
    offset = 0
    for _ in range(8):
        snapshot = yield Goto(f"{base()}{project}/-/commits/main?author={query}&offset={offset}")
        rows = _commit_rows(snapshot)
        days += [d for d, author in rows if _same_person(author, user)]
        commits = len(snapshot.css("li.commit"))
        if commits < 40 or (until and rows and rows[-1][0] < until):
            break
        offset += 40
    return days


def _date(text: str) -> tuple[int | None, int, int]:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*", text)
    if m is not None:
        return (int(m.group(3)) if m.group(3) else None), int(m.group(1)), int(m.group(2))
    day = parse_due(text)
    return day.year, day.month, day.day


def commits_on(user: str, date_text: str, repo: str = "") -> Skill[str]:
    if repo:
        project = yield from find_project(repo)
    else:
        snapshot = yield Hover(Locator.css("body"))
        project = _project_of(snapshot.url)
    year, month, day = _date(date_text)
    total = 0
    until = date(year, month, day) if year is not None else None
    for name in re.split(r"\s+and\s+|,\s*", user.strip()):
        days = yield from _commits_by(project, name, until)
        matching = [
            d
            for d in days
            if d.month == month and d.day == day and (year is None or d.year == year)
        ]
        if year is None and matching:
            matching = [d for d in matching if d == max(matching)]
        total += len(matching)
    return str(total)


def commits_during(user: str, period: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    text = re.sub(r"^(?:durning|during|in)\s+", "", period.strip(), flags=re.I)
    if m := re.fullmatch(r"between\s+(.+?)\s*(?:\s+and\s+|-)\s*(.+)", text, flags=re.I):
        try:
            start, end = period_range(m.group(1)).start, period_range(m.group(2)).end
        except Unsupported:
            raise Precondition(f"unsupported period {period!r}") from None
    else:
        try:
            span = period_range(text)
        except Unsupported:
            raise Precondition(f"unsupported period {period!r}") from None
        start, end = span.start, span.end
    days = yield from _commits_by(project, user, start)
    return str(sum(1 for d in days if start <= d <= end))


def parse_contributors(snapshot: PageSnapshot) -> list[Contributor]:
    found = []
    for h4 in snapshot.css(".contributors-charts h4"):
        nxt = h4.getnext()
        if nxt is None:
            continue
        m = re.fullmatch(r"(\d+) commits? \(([^)]+)\)", " ".join(nxt.text_content().split()))
        if m:
            found.append(
                Contributor(" ".join(h4.text_content().split()), int(m.group(1)), m.group(2))
            )
    return sorted(found, key=lambda c: -c.commits)


def _graph_branch(project: str, branch: str) -> Skill[str]:
    # "main" where the project has no such branch is its default branch, which the Contributors
    # link on the project page names; "gh-page" is the gh-pages branch
    if branch:
        snapshot = yield Goto(f"{base()}{project}/-/branches/all?search={quote_plus(branch)}")
        names = [
            " ".join(a.text_content().split()) for a in snapshot.css("li.branch-item .item-title")
        ]
        close = sorted((n for n in names if n.startswith(branch)), key=len)
        if close:
            return close[0]
    snapshot = yield Goto(f"{base()}{project}")
    for a in snapshot.css("a[href*='/-/graphs/']"):
        if m := re.search(r"/-/graphs/([^/?#]+)$", str(a.get("href"))):
            return m.group(1)
    raise Postcondition(f"no contributors link on {project}")


CHART_WAITS = 12


def _contributors(project: str, branch: str = "") -> Skill[list[Contributor]]:
    # the chart page draws its contributor list by script, which takes some seconds on a large
    # history; the observations in between only wait
    name = yield from _graph_branch(project, branch)
    snapshot = yield Goto(f"{base()}{project}/-/graphs/{name}")
    people = parse_contributors(snapshot)
    for n in range(CHART_WAITS):
        if people:
            break
        snapshot = yield settle(n)
        people = parse_contributors(snapshot)
    return people


@dataclass(frozen=True)
class Profile:
    name: str
    username: str
    location: str
    followers: str


def _profile(person: Contributor) -> Skill[Profile]:
    snapshot = yield Goto(f"{base()}/search?search={quote_plus(person.name)}&scope=users")
    handle = ""
    for a in snapshot.css(".search-results li a"):
        text = " ".join(a.text_content().split())
        if text.lower().startswith(person.name.lower() + " @"):
            handle = text.split(" @")[-1]
            break
    if not handle:
        raise Precondition(f"no account named {person.name!r}")
    snapshot = yield Goto(f"{base()}/{handle}")
    followers = re.match(r"\d+", snapshot.text(f"a[href$='/{handle}/followers']") or "")
    return Profile(
        snapshot.text("[itemprop=name]") or person.name,
        handle,
        snapshot.text("[itemprop=addressLocality]") or "",
        followers.group(0) if followers else "",
    )


def _describe(person: Contributor, attribute: str) -> str:
    key = attribute.lower()
    if "email" in key:
        return person.email
    if "last name" in key:
        return person.name.split()[-1]
    if "number" in key or "commits" in key:
        return f"{person.name}: {person.commits}" if "name" in key else str(person.commits)
    return person.name


def top_contributor(repo: str) -> Skill[str]:
    project = yield from find_project(repo)
    people = yield from _contributors(project)
    if not people:
        raise Postcondition(f"no contributors listed for {project}")
    return people[0].name


def top_contributors(attribute: str, repo: str) -> Skill[str]:
    project = yield from find_project(repo)
    people = yield from _contributors(project)
    if not people:
        raise Postcondition(f"no contributors listed for {project}")
    return ", ".join(_describe(c, attribute) for c in people[:3])


def branch_top_contributor(attribute: str, branch_name: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    people = yield from _contributors(project, branch_name)
    if not people:
        raise Postcondition(f"no contributors listed for {project} on {branch_name}")
    key = attribute.lower()
    if not any(w in key for w in ("account", "location", "follower")):
        return _describe(people[0], attribute)
    profile = yield from _profile(people[0])
    if "follower" in key:
        return profile.followers
    parts = []
    for field in re.split(r"\s*(?:,|\band\b)\s*", key):
        if "account" in field or "user" in field:
            parts.append(profile.username)
        elif "location" in field:
            parts.append(profile.location)
        elif "email" in field:
            parts.append(people[0].email)
        elif "name" in field:
            parts.append(profile.name)
    return ", ".join(p for p in parts if p)


def starred_repositories(description: str) -> Skill[str]:
    rows = yield from my_projects()
    text = description.lower()
    if m := re.search(r"more than (\d+)", text):
        chosen = [r for r in rows if r.stars > int(m.group(1))]
    elif m := re.search(r"(?:less|fewer) than (\d+)", text):
        chosen = [r for r in rows if r.stars < int(m.group(1))]
    elif "most" in text:
        top = max(r.stars for r in rows)
        chosen = [r for r in rows if r.stars == top]
    elif "least" in text or "fewest" in text:
        low = min(r.stars for r in rows)
        chosen = [r for r in rows if r.stars == low]
    elif text.strip() in ("no", "zero", "0"):
        chosen = [r for r in rows if r.stars == 0]
    elif m := re.search(r"(\d+)", text):
        chosen = [r for r in rows if r.stars == int(m.group(1))]
    else:
        raise Precondition(f"unsupported description {description!r}")
    return ", ".join(r.name for r in chosen) if chosen else "N/A"


def _titled(title: str, keyword: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return all(
        any(same_word(w, t) for t in tokens) for w in re.findall(r"[a-z0-9]+", keyword.lower())
    )


def _latest_issue(keyword: str, sort: str) -> Skill[bool | None]:
    # the dashboard issue list, filtered to my own issues with the keyword, newest first; the
    # search also matches descriptions, so the title is checked here. When none of my issues
    # carries the keyword in its title, everyone's are searched ("Tm Theme Editor" was opened
    # by another user in my project)
    links: list[str] = []
    for author in (f"&author_username={ME}", ""):
        url = (
            f"{base()}/dashboard/issues?scope=all&state=all{author}"
            f"&search={quote_plus(keyword)}&sort={sort}"
        )
        snapshot = yield Goto(url)
        links = [
            str(a.get("href"))
            for li in snapshot.css("li.issue")
            for a in li.cssselect("a[href*='/-/issues/']")
            if a.get("href") and _titled(" ".join(a.text_content().split()), keyword)
        ]
        if not author:
            links = [h for h in links if f"/{ME}/" in h]
        if links:
            break
    if not links:
        return None
    href = str(links[0])
    snapshot = yield Goto(href if href.startswith("http") else f"{base()}{href}")
    shown = [
        e
        for e in snapshot.css(".issuable-status-badge")
        if "hidden" not in str(e.get("class", "")).split()
    ]
    return any("issuable-status-badge-closed" in str(e.get("class", "")) for e in shown)


def latest_updated_issue(keyword: str) -> Skill[str]:
    closed = yield from _latest_issue(keyword, "updated_desc")
    if closed is None:
        return "N/A"
    return "Yes" if closed else "No"


def latest_created_issue(keyword: str) -> Skill[str]:
    closed = yield from _latest_issue(keyword, "created_date")
    if closed is None:
        return "N/A"
    return "Yes" if closed else "No"


def parse_members(snapshot: PageSnapshot) -> list[str]:
    names = []
    for tr in snapshot.css("table tbody tr"):
        m = re.search(r"@([\w.-]+)", " ".join(tr.text_content().split()))
        if m:
            names.append(m.group(1))
    return names


def who_has_access(repo: str) -> Skill[str]:
    project = yield from find_project(repo)
    snapshot = yield Goto(f"{base()}{project}/-/project_members")
    others = [n for n in parse_members(snapshot) if n != ME]
    return ", ".join(others) if others else "N/A"


def feed_token() -> Skill[str]:
    # the token is masked on the tokens page; the dashboard's atom link carries it
    snapshot = yield Goto(f"{base()}/dashboard/projects")
    m = re.search(r"feed_token=([A-Za-z0-9_-]+)", snapshot.html)
    if m is None:
        raise Postcondition("no feed token link on the dashboard")
    return m.group(1)


def star_top(number: str) -> Skill[str]:
    count = NUMBERS.get(number.strip().lower()) or int(number)
    snapshot = yield Goto(f"{base()}/explore/projects?sort=stars_desc")
    rows = parse_projects(snapshot)[:count]
    if len(rows) < count:
        raise Postcondition(f"only {len(rows)} projects listed")
    for row in rows:
        snapshot = yield Goto(f"{base()}{row.path}")
        if "Unstar" in (snapshot.text("button.star-btn") or ""):
            continue
        yield Click(Locator.css("button.star-btn"))
    return ""


def follow_users(account_list: str) -> Skill[str]:
    names = re.findall(r"'([^']+)'|\"([^\"]+)\"", account_list)
    people = [a or b for a, b in names] or [n.strip() for n in account_list.strip("[]").split(",")]
    for person in people:
        snapshot = None
        if re.fullmatch(r"[\w.-]+", person.strip()):
            snapshot = yield Goto(f"{base()}/{person.strip()}")
        if snapshot is None or "Not Found" in (snapshot.text("title") or ""):
            username = yield from user_handle(person)
            snapshot = yield Goto(f"{base()}/{username}")
        if "Unfollow" in snapshot.html.split("profile-header")[-1][:4000]:
            continue
        yield Click(Locator.css("form[action$='/follow.json'] button"))
    return ""


REGISTRY["gitlab.todos"] = todos
REGISTRY["gitlab.merge_requests_assigned"] = merge_requests_assigned
REGISTRY["gitlab.merge_requests_to_review"] = merge_requests_to_review
REGISTRY["gitlab.explore"] = explore
REGISTRY["gitlab.recent_open_issues"] = recent_open_issues
REGISTRY["gitlab.issues_by_label"] = issues_by_label
REGISTRY["gitlab.open_issues_about"] = open_issues_about
REGISTRY["gitlab.clone_command"] = clone_command
REGISTRY["gitlab.commits_on"] = commits_on
REGISTRY["gitlab.commits_during"] = commits_during
REGISTRY["gitlab.top_contributor"] = top_contributor
REGISTRY["gitlab.top_contributors"] = top_contributors
REGISTRY["gitlab.branch_top_contributor"] = branch_top_contributor
REGISTRY["gitlab.starred_repositories"] = starred_repositories
REGISTRY["gitlab.latest_updated_issue"] = latest_updated_issue
REGISTRY["gitlab.latest_created_issue"] = latest_created_issue
REGISTRY["gitlab.who_has_access"] = who_has_access
REGISTRY["gitlab.feed_token"] = feed_token
REGISTRY["gitlab.star_top"] = star_top
REGISTRY["gitlab.follow_users"] = follow_users
