import os
from datetime import date
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Goto
from lk47.skills.gitlab.common import parse_due, parse_projects, relative_to, user_handle
from lk47.skills.gitlab.write import license_template
from lk47.skills.gitlab.read import (
    _commit_rows,
    _same_person,
    feed_token,
    parse_contributors,
    parse_members,
    resolve_label,
)
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/gitlab"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


@pytest.fixture(autouse=True)
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "GITLAB", "http://localhost:8023")


def test_project_rows_carry_path_name_and_stars() -> None:
    rows = parse_projects(snapshot("explore_projects_sort-stars_desc.html"))
    assert rows[0].path == "/umano/AndroidSlidingUpPanel" and rows[0].stars == 55
    assert [r.name for r in rows[:3]] == ["AndroidSlidingUpPanel", "create-react-app", "ffmpeg-python"]
    mine = parse_projects(snapshot("dashboard_projects.html"))
    assert any(r.path == "/a11yproject/a11yproject.com" for r in mine) and len(mine) == 14
    patterns = next(r for r in mine if r.path == "/byteblaze/accessible-html-content-patterns")
    assert "HTML5" in patterns.description


def test_contributors_are_ranked_by_commits() -> None:
    people = parse_contributors(snapshot("graphs_a11y.html"))
    assert people[0].name == "Eric Bailey" and people[0].commits == 422
    assert people[0].email == "eric.w.bailey@gmail.com"
    assert people[1].commits == 410 and people[1].email == "ericwbailey@users.noreply.github.com"


def test_commit_rows_carry_day_and_author() -> None:
    rows = _commit_rows(snapshot("commits_a11y_kilian.html"))
    assert rows[0] == (date(2023, 3, 5), "Kilian Valkhof") and len(rows) == 3
    assert _same_person("Steve Woodson", "Steven Woodson")
    assert _same_person("Kilian Valkhof", "kilian")
    assert not _same_person("Erica Smith", "Eric")
    assert not _same_person("Nicolas Steenhout", "Nic")
    assert parse_members(snapshot("members_a11y.html")) == ["byteblaze", "Roshanjossey", "a11yproject"]


def test_labels_and_dates() -> None:
    names = ["help wanted", "question", "bug", "type: bug 🐞", "good first issue"]
    assert resolve_label(names, "help needed") == "help wanted"
    assert resolve_label(names, "questions") == "question"
    assert resolve_label(names[:3], "bugs") == "bug"
    assert parse_due("the end of 2030") == date(2030, 12, 31)
    assert parse_due("the beginning of Q2 2033") == date(2033, 4, 1)
    assert parse_due("1/16/2023") == date(2023, 1, 16)
    assert parse_due("end of 08/2022") == date(2022, 8, 31)
    assert relative_to(date(2023, 1, 16), "in 20 days") == date(2023, 2, 5)


def test_feed_token_comes_from_the_dashboard_link() -> None:
    skill = feed_token()
    assert isinstance(next(skill), Goto)
    with pytest.raises(StopIteration) as done:
        skill.send(snapshot("dashboard.html"))
    assert len(done.value.value) == 20


def test_licence_wordings_name_their_template() -> None:
    assert license_template("Make the LICENSE of dotfiles to MIT license.") == "MIT License"
    assert license_template("to Apache License") == "Apache License 2.0"
    assert license_template("to one that mandates all copies and derivative works to be under the same license") == "GNU General Public License v3.0"


def test_typed_text_keeps_characters_outside_the_harness_keys() -> None:
    from lk47.actions import Locator, Type, render, to_harness

    act = Type(Locator.css("textarea#note"), "Didn\u2019t last \u2013 \u201cfine\u201d")
    code = render(act)
    assert code == 'page.locator("textarea#note").fill("Didn\\u2019t last \\u2013 \\u201cfine\\u201d")'
    to_harness(act)


def test_user_handle_matches_every_word_of_a_partial_name() -> None:
    html = (
        "<html><body><a href='/byteblaze'>@byteblaze</a><ul class='search-results'>"
        "<li><a href='/jirutka'>Jakub Jirutka @jirutka</a></li>"
        "<li><a href='/lahwaacz'>Jakub Klinkovsk\u00fd @lahwaacz</a></li></ul></body></html>"
    )
    page = PageSnapshot("fixture://users", html, "", 1, lxml.html.fromstring(html))
    for name, handle in (("Jakub K", "lahwaacz"), ("Jakub", "jirutka"), ("jirutka", "jirutka")):
        skill = user_handle(name)
        assert isinstance(next(skill), Goto)
        with pytest.raises(StopIteration) as done:
            skill.send(page)
        assert done.value.value == handle
