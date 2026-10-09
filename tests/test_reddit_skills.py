import os
from pathlib import Path

import lxml.html
import pytest

from lk47.actions import Click, Goto, Type
from lk47.skills.reddit.forums import (
    create_forum,
    parse_comments,
    parse_submissions,
    resolve_forum,
    submit_post,
)
from lk47.snapshot import PageSnapshot

FIXTURES = Path(__file__).parent / "fixtures/reddit"


def snapshot(name: str, step: int = 1) -> PageSnapshot:
    html = (FIXTURES / name).read_text()
    return PageSnapshot(f"fixture://{name}", html, "", step, lxml.html.fromstring(html))


@pytest.fixture(autouse=True)
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "REDDIT", "http://forum.invalid")


def names() -> list[str]:
    return [a.text_content().strip() for a in snapshot("forums_all.html").css("a[href^='/f/']")]


@pytest.mark.parametrize(
    ("phrase", "forum"),
    [
        ("books", "books"),
        ("r/headphones", "headphones"),
        ("future technology", "technology"),
        ("gaming consoles", "consoles"),
        ("what is the recommended console to buy these days", "consoles"),
        ("is car necessary in NYC", "nyc"),
        ("city Pittsburgh", "pittsburgh"),
        ("relations", "relationship_advice"),
        ("Iphone 14", "iphone"),
        ("Harry Potter movie series", "movies"),
        ("noise-cancelling headphones", "headphones"),
        ("DIY toolkit", "DIY"),
        ("the effectiveness of online learning", "deeplearning"),
        ("earthporn", "EarthPorn"),
    ],
)
def test_forums_resolve_from_the_list(phrase: str, forum: str) -> None:
    assert resolve_forum(names(), phrase) == forum


def test_submissions_and_comments_parse() -> None:
    posts = parse_submissions(snapshot("f_books.html"))
    assert len(posts) == 25
    assert posts[0].submitter == "RunDNA" and posts[0].forum == "books"
    assert posts[0].path.startswith("/f/books/81371/") and posts[0].choice == 0 and posts[0].score == 3591
    mine = parse_submissions(snapshot("user_me.html"))
    assert mine[0].title == "Nvidia RTX 4090" and mine[0].forum == "MachineLearning"
    comments = parse_comments(snapshot("user_MarvelsGrantMan136_comments.html"))
    assert len(comments) == 25 and comments[0].score == 14 and comments[0].author == "MarvelsGrantMan136"


def test_posting_and_forum_creation_actions() -> None:
    skill = submit_post("books", "Harry Potter", "Wonderful journey")
    first = next(skill)
    assert isinstance(first, Goto) and first.url == "http://forum.invalid/submit/books"
    typed = [skill.send(snapshot("submit_books.html")), skill.send(snapshot("submit_books.html"))]
    assert [t.text for t in typed if isinstance(t, Type)] == ["Harry Potter", "Wonderful journey"]
    assert isinstance(skill.send(snapshot("submit_books.html")), Click)
    skill = create_forum("sci_fi", "A wild place", "['New', 'Classic', 'Post my novel']")
    next(skill)
    acts = [skill.send(snapshot("create_forum.html")) for _ in range(4)]
    assert [a.text for a in acts if isinstance(a, Type)] == ["sci_fi", "sci_fi", "A wild place", "New, Classic, Post my novel"]


def test_dislike_plan_votes_down_and_vote_state_is_read_from_the_form_class() -> None:
    from lk47.intents import parse
    from lk47.plan import build
    from lk47.skills.reddit.forums import _form_has

    plan = build(parse("DisLike all submissions created by jacyanthis in subreddit earthporn"))
    assert plan.calls[0].literals == {"up": "no"}
    plan = build(parse("Like all submissions created by CameronKelsey in subreddit earthporn"))
    assert plan.calls[0].literals == {}
    page = snapshot("post_books.html")
    assert not _form_has(page, "vote--user-upvoted") and not _form_has(page, "vote--user-downvoted")
    assert "vote--user-upvoted" in page.html
