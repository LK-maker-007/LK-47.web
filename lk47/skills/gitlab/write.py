from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote_plus

from lk47.actions import Click, Goto, Hover, Locator, Press, Type
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill, settle
from lk47.skills.forms import choose_option, replace_text
from lk47.skills.gitlab.common import (
    ME,
    base,
    find_project,
    iso,
    parse_due,
    parse_projects,
    relative_to,
    user_handle,
)
from lk47.skills.gitlab.read import _graph_branch, _project_of
from lk47.skills.shopping_admin.products import same_word
from lk47.snapshot import PageSnapshot

VISIBILITY = {"private": "0", "internal": "10", "public": "20"}


def set_status(status: str) -> Skill[str]:
    # the named status field is hidden; the visible box is a separate input that copies into it
    yield Goto(f"{base()}/-/profile")
    yield from replace_text(Locator.placeholder("What's your status?"), status)
    snapshot = yield Click(Locator.role("button", name="Update profile settings"))
    if "Profile was successfully updated" not in snapshot.html:
        snapshot = yield Hover(Locator.css("body"))
    if "Profile was successfully updated" not in snapshot.html:
        raise Postcondition("profile not updated")
    return ""


def set_homepage(url: str) -> Skill[str]:
    if not re.match(r"https?://", url):
        url = f"http://{url}"
    yield Goto(f"{base()}/-/profile")
    yield from replace_text(Locator.css("input[name='user[website_url]']"), url)
    snapshot = yield Click(Locator.role("button", name="Update profile settings"))
    if "Profile was successfully updated" not in snapshot.html:
        snapshot = yield Hover(Locator.css("body"))
    if "Profile was successfully updated" not in snapshot.html:
        raise Postcondition("profile not updated")
    return ""


def _names(account_list: str) -> list[str]:
    quoted = [a or b for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", account_list)]
    if quoted:
        return quoted
    return [n.strip() for n in re.split(r",|\band\b", account_list.strip("[]")) if n.strip()]


def _can_invite(project: str) -> Skill[bool]:
    snapshot = yield Goto(f"{base()}{project}/-/project_members")
    buttons = [" ".join(b.text_content().split()) for b in snapshot.css("button")]
    return "Invite members" in buttons


def _invite(project: str, names: list[str], role: str = "") -> Skill[None]:
    for name in names:
        try:
            handle = yield from user_handle(name)
        except Precondition:
            handle = name
        yield Goto(f"{base()}{project}/-/project_members")
        yield Click(Locator.role("button", name="Invite members"))
        yield Type(Locator.css(".modal input[id$='_search']"), handle)
        yield Click(Locator.css(".modal button.dropdown-item").nth(0))
        if role:
            yield from choose_option(Locator.css(".modal select"), role.capitalize())
        snapshot = yield Click(Locator.css(".modal button").having_text("Invite"))
        if (
            "successfully" not in snapshot.html.lower()
            and handle.lower() not in snapshot.html.lower()
        ):
            raise Postcondition(f"{name} not invited to {project}")


def _own_namespace(pane: str) -> Skill[None]:
    # the form fills in my namespace only while I own no group; once I own one it asks
    # "Pick a group or namespace" and refuses to submit without it
    yield Click(
        Locator.css(f"{pane} [data-qa-selector='select_namespace_dropdown'] button.dropdown-toggle")
    )
    yield Click(Locator.css(f"{pane} .dropdown-menu.show button.dropdown-item").having_text(ME))


def new_project(project_name: str, scope: str = "private", account_list: str = "") -> Skill[str]:
    level = VISIBILITY.get(scope.strip().lower(), "0")
    pane = "#blank-project-pane"
    yield Goto(f"{base()}/projects/new#blank_project")
    yield Type(Locator.css(f"{pane} input[name='project[name]']"), project_name)
    yield from _own_namespace(pane)
    yield Click(Locator.css(f"{pane} input#project_visibility_level_{level} + label"))
    snapshot = yield Click(Locator.css(f"{pane} button[type='submit']"))
    if f"/{ME}/" not in snapshot.url:
        snapshot = yield Hover(Locator.css("body"))
    if f"/{ME}/" not in snapshot.url:
        raise Postcondition(f"project not created, at {snapshot.url}")
    project = _project_of(snapshot.url)
    if account_list:
        yield from _invite(project, _names(account_list))
    return ""


def _template_key(snapshot: PageSnapshot, template: str) -> str:
    wanted = template.strip().lower()
    for option in snapshot.css("#create-from-template-pane .template-option"):
        name = " ".join(option.cssselect(".description strong")[0].text_content().split()).lower()
        radio = option.cssselect("input[name='project[template_name]']")
        if radio and wanted in re.findall(r"[a-z0-9]+", name.replace(".", "")):
            return str(radio[0].get("value"))
    raise Precondition(f"no project template named {template!r}")


def new_template_project(
    project_name: str, template: str, account_list: str = "", scope: str = "private"
) -> Skill[str]:
    if template.strip().lower() == "blank":
        return (yield from new_project(project_name, scope, account_list))
    snapshot = yield Goto(f"{base()}/projects/new#create_from_template")
    key = _template_key(snapshot, template)
    level = VISIBILITY.get(scope.strip().lower(), "0")
    pane = "#create-from-template-pane"
    yield Click(Locator.css(f"label[for='{key}']").nth(0))
    yield Type(Locator.css(f"{pane} input[name='project[name]']"), project_name)
    yield from _own_namespace(pane)
    yield Click(Locator.css(f"{pane} input#project_visibility_level_{level} + label"))
    snapshot = yield Click(Locator.css(f"{pane} button[type='submit']"))
    for n in range(6):
        if f"/{ME}/" in snapshot.url and "/-/import" not in snapshot.url:
            break
        snapshot = yield settle(n)
    else:
        raise Postcondition(f"project not created, at {snapshot.url}")
    if account_list:
        yield from _invite(_project_of(snapshot.url), _names(account_list))
    return ""


def _owner_path(owner: str) -> Skill[str]:
    text = owner.strip()
    if re.fullmatch(r"[\w.-]+", text):
        snapshot = yield Goto(f"{base()}/{text}")
        if "Not Found" not in (snapshot.text("title") or ""):
            return f"/{text}"
    snapshot = yield Goto(f"{base()}/search?search={quote_plus(text)}&scope=users")
    links = [str(a.get("href")) for a in snapshot.css(".search-results li .avatar-cell a")]
    if not links:
        raise Precondition(f"no user or group named {owner!r}")
    return links[0]


def _fork_into_mine(project: str) -> Skill[None]:
    yield Goto(f"{base()}{project}/-/forks/new")
    yield Click(Locator.role("button", name="Select a namespace"))
    yield Click(Locator.css(".dropdown-menu li button, .dropdown-item").having_text(ME))
    snapshot = yield Click(Locator.role("button", name="Fork project"))
    # the fork imports for a few seconds on an /-/import page that redirects itself when done;
    # a navigation started before then is overridden by that redirect
    for n in range(12):
        if f"/{ME}/" in snapshot.url and "/-/import" not in snapshot.url:
            return
        snapshot = yield settle(n)
    raise Postcondition(f"fork of {project} not finished, at {snapshot.url}")


def fork_all(owner: str, source_only: str = "") -> Skill[str]:
    path = yield from _owner_path(owner)
    snapshot = yield Goto(f"{base()}/users{path}/projects")
    for n in range(3):
        if parse_projects(snapshot):
            break
        snapshot = yield settle(n)
    projects = list(dict.fromkeys(r.path for r in parse_projects(snapshot)))
    if not projects:
        raise Postcondition(f"no projects listed for {owner!r}")
    for project in projects:
        if source_only:
            page = yield Goto(f"{base()}{project}")
            if "Forked from" in " ".join((page.text("body") or "").split()):
                continue
        yield from _fork_into_mine(project)
    yield Goto(f"{base()}/dashboard/projects")
    return ""


def fork(repo: str) -> Skill[str]:
    if m := re.fullmatch(
        r"all\s+(source\s+)?(?:repos|repositories|projects)\s+(?:from|of|by)\s+(.+)",
        repo.strip(),
        flags=re.I,
    ):
        return (yield from fork_all(m.group(2), "yes" if m.group(1) else ""))
    words = re.sub(r"(?i)\bthe\b|\bwith most stars\b|\brepo\b", "", repo).strip()
    project = yield from find_project(words or repo, others_only=True)
    yield from _fork_into_mine(project)
    return ""


def _type_lines(editor: Locator, lines: list[str]) -> Skill[None]:
    # the editor suggests completions while a line is typed and Enter would accept one, so
    # Escape closes the suggestion before Enter breaks the line
    for line in lines:
        yield Type(editor, line)
        yield Press("Escape")
        yield Press("Enter")


def create_file(project: str, path: str, lines: list[str]) -> Skill[None]:
    yield Goto(f"{base()}{project}/-/new/main")
    yield Type(Locator.css("#file_name"), path)
    editor = Locator.css(".monaco-editor textarea.inputarea")
    yield from _type_lines(editor, lines)
    snapshot = yield Click(Locator.css("#commit-changes"))
    if f"/-/blob/main/{path}" not in snapshot.url:
        snapshot = yield Hover(Locator.css("body"))
    if f"/-/blob/main/{path}" not in snapshot.url:
        raise Postcondition(f"file {path} not committed, at {snapshot.url}")


def edit_file(project: str, path: str, lines: list[str]) -> Skill[None]:
    yield Goto(f"{base()}{project}/-/edit/main/{path}")
    editor = Locator.css(".monaco-editor textarea.inputarea")
    yield Click(editor)
    yield Press("Control+a")
    yield from _type_lines(editor, lines)
    snapshot = yield Click(Locator.css("#commit-changes"))
    if f"/-/blob/main/{path}" not in snapshot.url:
        snapshot = yield Hover(Locator.css("body"))
    if f"/-/blob/main/{path}" not in snapshot.url:
        raise Postcondition(f"file {path} not committed, at {snapshot.url}")


LICENSE_TEMPLATES = (
    ("mit", "MIT License"),
    ("apache", "Apache License 2.0"),
    ("same license", "GNU General Public License v3.0"),
    ("derivative", "GNU General Public License v3.0"),
    ("gpl", "GNU General Public License v3.0"),
)
LICENSE_FILE = re.compile(r"(licen[sc]e|copying)(\..*)?", re.I)


def license_template(text: str) -> str:
    lowered = text.lower()
    for word, name in LICENSE_TEMPLATES:
        if word in lowered:
            return name
    raise Precondition(f"no licence template for {text!r}")


def _json(snapshot: PageSnapshot) -> Any:
    try:
        return json.loads(snapshot.text("pre") or snapshot.text("body") or "")
    except json.JSONDecodeError:
        raise Postcondition(f"no JSON at {snapshot.url}") from None


def _licence_text(project: str, template: str) -> Skill[list[str]]:
    listing = _json((yield Goto(f"{base()}/api/v4/templates/licenses?per_page=100")))
    keys = {t["name"]: t["key"] for t in listing}
    if template not in keys:
        raise Precondition(f"no licence template named {template!r}")
    holder = _json((yield Goto(f"{base()}/api/v4/user")))["name"]
    content = _json(
        (
            yield Goto(
                f"{base()}/api/v4/templates/licenses/{keys[template]}"
                f"?project={quote_plus(project.rsplit('/', 1)[-1])}&fullname={quote_plus(holder)}"
            )
        )
    )["content"]
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", content) if p.strip()]


def _type_paragraphs(editor: Locator, paragraphs: list[str]) -> Skill[None]:
    for i, paragraph in enumerate(paragraphs):
        yield Type(editor, paragraph)
        yield Press("Escape")
        if i < len(paragraphs) - 1:
            yield Press("Enter")
            yield Press("Enter")


def set_license(repo: str, license: str) -> Skill[str]:  # noqa: A002  slot name from the template
    template = license_template(license)
    editor = Locator.css(".monaco-editor textarea.inputarea")
    for name in re.split(r"\s*(?:,|\band\b)\s*", repo.strip()):
        project = yield from find_project(name)
        snapshot = yield Goto(f"{base()}{project}")
        if not snapshot.css("a[href*='/-/blob/']"):
            snapshot = yield Hover(Locator.css("body"))
        files = [
            (str(a.get("href")), " ".join(a.text_content().split()))
            for a in snapshot.css("a[href*='/-/blob/']")
        ]
        branches = [m.group(1) for href, _ in files if (m := re.search(r"/-/blob/([^/]+)/", href))]
        if not branches:
            raise Postcondition(f"no files listed for {project}")
        existing = [(href, text) for href, text in files if LICENSE_FILE.fullmatch(text)]
        if existing and existing[0][1] != "LICENSE":
            # the template picker renames the file to LICENSE, and the file name field then
            # hands every key to the picker; LICENSE.txt is rewritten by typing the text instead
            href, path = existing[0]
            paragraphs = yield from _licence_text(project, template)
            edit = href.replace("/-/blob/", "/-/edit/")
            yield Goto(edit if edit.startswith("http") else f"{base()}{edit}")
            yield Click(editor)
            yield Press("Control+a")
            yield from _type_paragraphs(editor, paragraphs)
        else:
            if existing:
                href, path = existing[0]
                edit = href.replace("/-/blob/", "/-/edit/")
                yield Goto(edit if edit.startswith("http") else f"{base()}{edit}")
            else:
                path = "LICENSE"
                yield Goto(f"{base()}{project}/-/new/{branches[0]}")
                yield Type(Locator.css("#file_name"), path)
            yield Click(Locator.css("button.js-license-selector"))
            snapshot = yield Click(
                Locator.css(".dropdown-menu.show a[data-group]").having_text(template)
            )
            first_word = template.split()[0].lower()
            for n in range(4):
                if first_word in (snapshot.text(".monaco-editor .view-lines") or "").lower():
                    break
                snapshot = yield settle(n)
            yield Click(editor)
            yield Press("Control+h")
            yield Type(Locator.css(".find-widget textarea[aria-label='Find']"), r"(\S)\n(\S)")
            yield Press("Alt+r")
            yield Type(Locator.css(".find-widget textarea[aria-label='Replace']"), "$1 $2")
            yield Press("Control+Alt+Enter")
        snapshot = yield Click(Locator.css("#commit-changes"))
        if f"/-/blob/{branches[0]}/{path}" not in snapshot.url:
            snapshot = yield Hover(Locator.css("body"))
        if f"/-/blob/{branches[0]}/{path}" not in snapshot.url:
            raise Postcondition(f"licence of {project} not committed, at {snapshot.url}")
    return ""


def set_site_title(title: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    raw = yield Goto(f"{base()}{project}/-/raw/main/index.html")
    pre = raw.css("pre")
    lines = pre[0].text_content().splitlines() if pre else []
    numbers = [i for i, line in enumerate(lines, 1) if "<title>" in line]
    if not numbers:
        raise Precondition(f"no title line in {project}/index.html")
    yield Goto(f"{base()}{project}/-/edit/main/index.html")
    editor = Locator.css(".monaco-editor textarea.inputarea")
    yield Click(editor)
    yield Press("Control+g")
    yield Type(Locator.css(".quick-input-widget input.input"), str(numbers[0]))
    yield Press("Enter")
    yield Press("Home")
    yield Press("Shift+End")
    yield Type(editor, f"<title>{title}</title>")
    yield Press("Escape")
    snapshot = yield Click(Locator.css("#commit-changes"))
    if "/-/blob/main/index.html" not in snapshot.url:
        snapshot = yield Hover(Locator.css("body"))
    if "/-/blob/main/index.html" not in snapshot.url:
        raise Postcondition(f"index.html not committed, at {snapshot.url}")
    return ""


def project_description(project: str) -> Skill[str]:
    snapshot = yield Goto(f"{base()}{project}")
    text = snapshot.text(".home-panel-description-markdown")
    if not text:
        raise Postcondition(f"no description on {project}")
    return text


def _create_issue(project: str, title: str, body: str, again: bool = False) -> Skill[None]:
    yield Goto(f"{base()}{project}/-/issues/new")
    title_field = Locator.css("input[name='issue[title]']")
    body_field = Locator.css("textarea[name='issue[description]']")
    if again:
        yield from replace_text(title_field, title)
        yield from replace_text(body_field, body)
        return
    yield Type(title_field, title)
    yield Type(body_field, body)


def open_issue(issue: str, repo: str) -> Skill[str]:
    try:
        project = yield from find_project(repo)
    except Precondition:
        return "N/A"
    text = re.sub(
        r"^(?:report|discuss)\s+(?:the issue of|experiencing|the)?\s*",
        "",
        issue.strip(),
        flags=re.I,
    )
    yield from _create_issue(project, text, issue.strip())
    snapshot = yield Click(Locator.role("button", name="Create issue"))
    if "/-/issues/" not in snapshot.url:
        raise Postcondition(f"issue not created, at {snapshot.url}")
    return ""


def discuss_issue(feature: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    yield from _create_issue(
        project, f"Implementation of {feature}", f"Let's discuss the implementation of {feature}."
    )
    snapshot = yield Click(Locator.role("button", name="Create issue"))
    if "/-/issues/" not in snapshot.url:
        raise Postcondition(f"issue not created, at {snapshot.url}")
    return ""


def _pick_user(search_button: str, account: str) -> Skill[list[str]]:
    missing = []
    yield Click(Locator.css(search_button))
    for part in re.split(r"\s*(?:,|\band\b)\s*", account.strip()):
        name = ME if part.lower() in ("myself", "me") else part
        yield from replace_text(Locator.css(".dropdown-menu.show input.dropdown-input-field"), name)
        snapshot = yield Hover(Locator.css("body"))
        first = name.split()[0].lower()
        offered = snapshot.css(".dropdown-menu.show a.dropdown-menu-user-link")
        if not any(first in e.text_content().lower() for e in offered):
            missing.append(name)
            continue
        entries = Locator.css(".dropdown-menu.show a.dropdown-menu-user-link")
        yield Click(entries.having_text(name.split()[0]).nth(0))
    return missing


def create_issue(repo: str, issue: str, account: str, due: str) -> Skill[str]:
    project = yield from find_project(repo)
    yield from _create_issue(project, issue, issue)
    yield Type(Locator.css("input[name='issue[due_date]']"), iso(parse_due(due)))
    missing = yield from _pick_user("button.js-assignee-search", account)
    if missing:
        yield from _invite(project, missing, "reporter")
        yield from _create_issue(project, issue, issue, again=True)
        yield from replace_text(Locator.css("input[name='issue[due_date]']"), iso(parse_due(due)))
        yield from _pick_user("button.js-assignee-search", account)
    snapshot = yield Click(Locator.role("button", name="Create issue"))
    if "/-/issues/" not in snapshot.url:
        raise Postcondition(f"issue not created, at {snapshot.url}")
    return ""


def assign_issue(issue: str, repo: str, account: str) -> Skill[str]:
    project = yield from find_project(repo)
    snapshot = yield Goto(f"{base()}{project}/-/issues/?search={quote_plus(issue)}&state=opened")
    links = [a.get("href") for a in snapshot.css("li.issue .issue-title-text")]
    if not links:
        raise Precondition(f"no open issue about {issue!r} in {project}")
    name = ME if account.strip().lower() in ("myself", "me") else account.strip()
    for href in [str(h) for h in links[:3]]:
        yield Goto(href if href.startswith("http") else f"{base()}{href}")
        yield Click(Locator.css(".block.assignee a.edit-link").nth(0))
        yield Type(Locator.css(".block.assignee input.dropdown-input-field"), name)
        yield Hover(Locator.css("body"))
        entries = Locator.css(".block.assignee a.dropdown-menu-user-link")
        yield Click(entries.having_text(name.split()[0]).nth(0))
        yield Click(Locator.css("h1"))
    return ""


def _edits(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


MR_TITLES = ".issuable-list li .merge-request-title-text a, .issuable-list li a.issue-title-text"
TOPIC_FILLERS = {"the", "and", "for", "with", "related", "about", "fixing", "adding"}


def _find_merge_request(project: str, topic: str) -> Skill[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 2]
    words = [w for w in words if w not in TOPIC_FILLERS] or words
    found: dict[str, str] = {}
    for word in sorted(words, key=len, reverse=True)[:3]:
        snapshot = yield Goto(
            f"{base()}{project}/-/merge_requests?search={quote_plus(word)}&state=all"
        )
        for a in snapshot.css(MR_TITLES):
            found.setdefault(str(a.get("href")), " ".join(a.text_content().split()))
        if found:
            break

    def hits(title: str) -> tuple[int, int]:
        tokens = re.findall(r"[a-z0-9]+", title.lower())
        close = sum(any(same_word(w, t) for t in tokens) for w in words)
        near = sum(any(len(w) >= 6 and _edits(w, t) <= 2 for t in tokens) for w in words)
        return close, near

    if not found:
        raise Precondition(f"no merge request about {topic!r} in {project}")
    href = max(found, key=lambda h: hits(found[h]))
    return href if href.startswith("http") else f"{base()}{href}"


def comment_merge_request(content: str, mr: str, repo: str) -> Skill[str]:
    project = yield from find_project(repo)
    url = yield from _find_merge_request(project, mr)
    form = "form.js-main-target-form"
    snapshot = yield Goto(url)
    for n in range(4):
        if snapshot.css(f"{form} textarea[name='note[note]']"):
            break
        snapshot = yield settle(n)
    for _ in range(2):
        yield Type(Locator.css(f"{form} textarea[name='note[note]']"), content)
        snapshot = yield Click(Locator.css(f"{form} button.split-content-button").nth(0))
        for n in range(3):
            if content in snapshot.html:
                return ""
            snapshot = yield settle(n)
    raise Postcondition("comment not posted")


def review_reply(topic: str) -> Skill[str]:
    links: list[str] = []
    for role in ("reviewer", "assignee"):
        snapshot = yield Goto(
            f"{base()}/dashboard/merge_requests?{role}_username={ME}&search={quote_plus(topic)}"
        )
        titles = (
            ".issuable-list li .merge-request-title-text a, .issuable-list li a.issue-title-text"
        )
        links = [str(a.get("href")) for a in snapshot.css(titles)]
        if links:
            break
    if not links:
        raise Precondition(f"no merge request to review about {topic!r}")
    href = links[0]
    snapshot = yield Goto(href if href.startswith("http") else f"{base()}{href}")
    author = snapshot.text("a.author-link") or ""
    comments = snapshot.css("#notes-list li.note-comment .note-header-author-name")
    last = " ".join(comments[-1].text_content().split()) if comments else ""
    handle = ""
    for a in snapshot.css("a.author-link"):
        m = re.match(r"/([\w.-]+)$", str(a.get("href") or ""))
        if m:
            handle = m.group(1)
            break
    text = "Thank you" if last and author and last == author else f"@{handle or author}"
    yield Type(Locator.css("textarea[name='note[note]']"), text)
    snapshot = yield Click(Locator.css("form.js-main-target-form button.split-content-button"))
    if text not in snapshot.html:
        raise Postcondition("reply not posted")
    return ""


BRANCH_FILLERS = {"the", "branch", "that", "implements", "support", "of", "for", "a", "an"}


def _branch(project: str, text: str, default: bool = False) -> Skill[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in BRANCH_FILLERS]
    query = quote_plus(max(words, key=len) if words else text.strip())
    snapshot = yield Goto(f"{base()}{project}/-/branches?state=all&search={query}")
    names = [
        str(a.get("href")).split("/-/tree/", 1)[1]
        for a in snapshot.css(".branch-item a[href*='/-/tree/']")
    ]
    if text.strip() in names:
        return text.strip()
    for name in names:
        tokens = re.findall(r"[a-z0-9]+", name.lower())
        if all(any(t.startswith(w) for t in tokens) for w in words):
            return name
    if default:
        return (yield from _graph_branch(project, ""))
    raise Precondition(f"no branch named by {text!r}")


def submit_merge_request(source_branch: str, target_branch: str, reviewer: str) -> Skill[str]:
    if "/" in source_branch:
        name, source_branch = source_branch.split("/", 1)
        project = yield from find_project(name)
    else:
        snapshot = yield Hover(Locator.css("body"))
        project = _project_of(snapshot.url)
    source_branch = yield from _branch(project, source_branch)
    target_branch = yield from _branch(project, target_branch, default=True)
    form = (
        f"{base()}{project}/-/merge_requests/new?merge_request%5Bsource_branch%5D={quote_plus(source_branch)}"
        f"&merge_request%5Btarget_branch%5D={quote_plus(target_branch)}"
    )
    yield Goto(form)
    missing = yield from _pick_user("button.js-reviewer-search", reviewer)
    if missing:
        yield from _invite(project, missing, "reporter")
        yield Goto(form)
        yield from _pick_user("button.js-reviewer-search", reviewer)
    snapshot = yield Click(Locator.role("button", name="Create merge request"))
    existing = re.search(r"already exists for this source branch: !(\d+)", snapshot.html)
    if existing:
        yield Goto(f"{base()}{project}/-/merge_requests/{existing.group(1)}")
        yield from _review_existing(reviewer)
        return ""
    if "/-/merge_requests/" not in snapshot.url:
        raise Postcondition(f"merge request not created, at {snapshot.url}")
    return ""


def _review_existing(reviewer: str) -> Skill[None]:
    block = ".block.reviewer"
    for part in re.split(r"\s*(?:,|\band\b)\s*", reviewer.strip()):
        if part.lower() in ("myself", "me"):
            yield Click(Locator.css(f"{block} button").having_text("assign yourself"))
            continue
        yield Click(Locator.css(f"{block} a.edit-link"))
        yield Type(Locator.css(f"{block} input.dropdown-input-field"), part)
        yield Hover(Locator.css("body"))
        yield Click(Locator.css(f"{block} a.dropdown-menu-user-link").having_text(part.split()[0]))
        yield Click(Locator.css("h1"))


def create_milestone(event: str, start_date: str, end_date: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    project = _project_of(snapshot.url)
    start = parse_due(start_date)
    end = relative_to(start, end_date)
    title = re.sub(r"^(?:event of|practice of)\s+", "", event.strip())
    title_field = Locator.css("input[name='milestone[title]']")
    yield Goto(f"{base()}{project}/-/milestones/new")
    yield Type(title_field, title)
    # each date field opens a calendar that keeps focus, and typing into the next field with
    # it open corrupts the first date, so the title is clicked after each date to close it
    yield Type(Locator.css("input[name='milestone[start_date]']"), iso(start))
    yield Click(title_field)
    yield Type(Locator.css("input[name='milestone[due_date]']"), iso(end))
    yield Click(title_field)
    snapshot = yield Click(Locator.role("button", name="Create milestone"))
    if "/-/milestones/" not in snapshot.url:
        raise Postcondition(f"milestone not created, at {snapshot.url}")
    return ""


def new_group(name: str, members: str) -> Skill[str]:
    yield Goto(f"{base()}/groups/new#create-group-pane")
    yield Type(Locator.css("input[name='group[name]']"), name)
    snapshot = yield Click(Locator.css("#create-group-pane button[type='submit']"))
    if f"/groups/{name}" not in snapshot.url and f"/{name}" not in snapshot.url:
        raise Postcondition(f"group not created, at {snapshot.url}")
    for person in _names(members):
        yield Goto(f"{base()}/groups/{name}/-/group_members")
        yield Click(Locator.role("button", name="Invite members"))
        yield Type(Locator.css(".modal input[id$='_search']"), person)
        yield Click(Locator.css(".modal button.dropdown-item").nth(0))
        yield Click(Locator.css(".modal button").having_text("Invite"))
    return ""


def invite_collaborators(collaborator_account_list: str, repo: str) -> Skill[str]:
    project = yield from find_project(repo)
    if not (yield from _can_invite(project)):
        return "N/A"
    yield from _invite(project, _names(collaborator_account_list))
    return ""


def invite_guest(name: str) -> Skill[str]:
    project = yield from find_project("dotfile")
    yield from _invite(project, [name], "guest")
    return ""


def add_members(repo: str, role: str, user_list: str) -> Skill[str]:
    project = yield from find_project(repo)
    if not (yield from _can_invite(project)):
        return "N/A"
    yield from _invite(project, _names(user_list), role)
    return ""


REGISTRY["gitlab.set_status"] = set_status
REGISTRY["gitlab.set_license"] = set_license
REGISTRY["gitlab.set_site_title"] = set_site_title
REGISTRY["gitlab.set_homepage"] = set_homepage
REGISTRY["gitlab.new_project"] = new_project
REGISTRY["gitlab.new_template_project"] = new_template_project
REGISTRY["gitlab.fork"] = fork
REGISTRY["gitlab.open_issue"] = open_issue
REGISTRY["gitlab.discuss_issue"] = discuss_issue
REGISTRY["gitlab.create_issue"] = create_issue
REGISTRY["gitlab.assign_issue"] = assign_issue
REGISTRY["gitlab.comment_merge_request"] = comment_merge_request
REGISTRY["gitlab.review_reply"] = review_reply
REGISTRY["gitlab.submit_merge_request"] = submit_merge_request
REGISTRY["gitlab.create_milestone"] = create_milestone
REGISTRY["gitlab.new_group"] = new_group
REGISTRY["gitlab.invite_collaborators"] = invite_collaborators
REGISTRY["gitlab.invite_guest"] = invite_guest
REGISTRY["gitlab.add_members"] = add_members
