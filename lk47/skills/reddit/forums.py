from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

from lk47.actions import Click, Goto, Hover, Locator, Press, Type
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import replace_text
from lk47.snapshot import PageSnapshot

ME = "MarvelsGrantMan136"
STOPWORDS = {
    "a",
    "an",
    "and",
    "about",
    "city",
    "for",
    "from",
    "in",
    "is",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "which",
    "with",
}


@dataclass(frozen=True)
class Submission:
    title: str
    link: str
    path: str
    submitter: str
    forum: str
    choice: int
    score: int


@dataclass(frozen=True)
class Comment:
    comment_id: str
    author: str
    body: str
    score: int
    path: str


def base() -> str:
    return site_url("REDDIT")


def parse_submissions(snapshot: PageSnapshot) -> list[Submission]:
    rows = []
    for art in snapshot.css("article.submission"):
        title = art.cssselect(".submission__title a")
        nav = [
            a.get("href")
            for a in art.cssselect(".submission__nav a")
            if (a.get("href") or "").startswith("/f/")
        ]
        vote = art.cssselect("form.vote")
        if not title or not nav or not vote:
            continue
        submitter = art.cssselect(".submission__submitter")
        forum = art.cssselect("a.submission__forum")
        forum_name = forum[0].text_content().strip() if forum else str(nav[0]).split("/")[2]
        rows.append(
            Submission(
                " ".join(title[0].text_content().split()),
                str(title[0].get("href") or ""),
                str(nav[0]),
                submitter[0].text_content().strip() if submitter else "",
                forum_name,
                int(vote[0].get("data-vote-choice-value") or 0),
                int(vote[0].get("data-vote-score-value") or 0),
            )
        )
    return rows


def parse_comments(snapshot: PageSnapshot) -> list[Comment]:
    rows = []
    for art in snapshot.css("article.comment"):
        vote = art.cssselect("form.vote")
        body = art.cssselect(".comment__body")
        author = art.cssselect(".comment__info a[href^='/user/']")
        links = [
            a.get("href")
            for a in art.cssselect(".comment__nav a")
            if "/comment/" in (a.get("href") or "")
        ]
        rows.append(
            Comment(
                (art.get("id") or "").removeprefix("comment_"),
                author[0].text_content().strip() if author else "",
                " ".join(body[0].text_content().split()) if body else "",
                int(vote[0].get("data-vote-score-value") or 0) if vote else 0,
                str(links[0]) if links else "",
            )
        )
    return rows


def forum_names() -> Skill[list[str]]:
    snapshot = yield Goto(f"{base()}/forums/all")
    names = [a.text_content().strip() for a in snapshot.css("a[href^='/f/']")]
    names = [n for n in names if n and " " not in n]
    if not names:
        raise Postcondition("no forums listed")
    return list(dict.fromkeys(names))


ABBREVIATIONS = {
    "ml": ["machinelearning"],
    "dl": ["deeplearning"],
    "nlp": ["machinelearning"],
    "ai": ["machinelearning"],
    "dmv": ["washingtondc"],
    "games": ["gaming"],
}


PHRASES = {"new york": "nyc", "new york city": "nyc"}


def _words(text: str) -> list[str]:
    lowered = text.lower()
    for phrase, forum in PHRASES.items():
        lowered = lowered.replace(phrase, forum)
    words = []
    for w in re.findall(r"[a-z0-9]+", lowered):
        if w in ABBREVIATIONS:
            words.extend(ABBREVIATIONS[w])
        elif w not in STOPWORDS and len(w) > 2:
            words.append(w)
    return words


def resolve_forum(names: list[str], phrase: str) -> str:
    # a forum named by a word of the phrase wins; then a forum whose name begins with a word or
    # contains it; ties go to the first forum in the alphabetical list
    cleaned = re.sub(r"^(?:r/|/f/|f/)", "", phrase.strip())
    for name in names:
        if name.lower() == cleaned.lower():
            return name
    words = _words(cleaned)
    best: tuple[int, int, str] | None = None
    for position, name in enumerate(names):
        low = name.lower()
        score = 0
        for w in words:
            if low == w:
                score = max(score, 400 + len(w))
            elif low.startswith(w) or (
                w.startswith(low) and len(low) >= 4 and w[len(low) :] == "s"
            ):
                score = max(score, 300 + len(w))
            elif any(ch.isdigit() for ch in w):
                continue
            elif w in low:
                score = max(score, 200 + len(w))
            elif len(w) >= 4 and low.startswith(w[:4]):
                score = max(score, 100 + len(w))
        if score and (best is None or (-score, position) < (best[0], best[1])):
            best = (-score, position, name)
    if best is None:
        raise Precondition(f"no forum matches {phrase!r}")
    return best[2]


def forum_for(phrase: str) -> Skill[str]:
    names = yield from forum_names()
    return resolve_forum(names, phrase)


def _vote(path: str, up: bool) -> Skill[None]:
    snapshot = yield Goto(f"{base()}{path}")
    posts = parse_submissions(snapshot)
    if not posts:
        raise Postcondition(f"no submission at {path}")
    wanted = 1 if up else -1
    if posts[0].choice == wanted:
        return
    button = ".vote__up" if up else ".vote__down"
    snapshot = yield Click(Locator.css(f"div.submission__vote form {button}"))
    # the form's class names the vote; its data attributes name both classes, so the html text
    # is no evidence
    marker = "vote--user-upvoted" if up else "vote--user-downvoted"
    if not _form_has(snapshot, marker):
        snapshot = yield Hover(Locator.css("body"))
    if not _form_has(snapshot, marker):
        raise Postcondition(f"vote not registered on {path}")


def _form_has(snapshot: PageSnapshot, marker: str) -> bool:
    forms = snapshot.css("div.submission__vote form")
    return bool(forms) and marker in (forms[0].get("class") or "")


def _user_submissions(user: str, pages: int = 6) -> Skill[list[Submission]]:
    snapshot = yield Goto(f"{base()}/user/{user}/submissions")
    posts = parse_submissions(snapshot)
    for _ in range(pages - 1):
        more = [a.get("href") for a in snapshot.css("a") if "More" in a.text_content()]
        if not more:
            break
        snapshot = yield Goto(str(more[0]))
        posts += parse_submissions(snapshot)
    return list({p.path: p for p in posts}.values())


def vote_user_submissions(user: str, subreddit: str, up: str = "yes") -> Skill[str]:
    try:
        forum = yield from forum_for(subreddit)
    except Precondition:
        return "N/A"
    posts = yield from _user_submissions(user)
    chosen = [p for p in posts if p.forum.lower() == forum.lower()]
    if not chosen:
        return "N/A"
    for post in chosen:
        yield from _vote(post.path, up == "yes")
    return ""


def upvote_newest(subreddit: str) -> Skill[str]:
    forum = yield from forum_for(subreddit)
    snapshot = yield Goto(f"{base()}/f/{forum}/new")
    posts = parse_submissions(snapshot)
    if not posts:
        raise Postcondition(f"no posts in {forum}")
    yield from _vote(posts[0].path, True)
    return ""


def thumbs_down_top(k: str, subreddit: str) -> Skill[str]:
    forum = yield from forum_for(subreddit)
    snapshot = yield Goto(f"{base()}/f/{forum}/top?t=all")
    posts = parse_submissions(snapshot)
    if len(posts) < int(k):
        raise Postcondition(f"fewer than {k} posts in {forum}")
    for post in posts[: int(k)]:
        yield from _vote(post.path, False)
    return ""


def subscribe_trending(subreddit: str) -> Skill[str]:
    forum = yield from forum_for(subreddit)
    snapshot = yield Goto(f"{base()}/f/{forum}")
    posts = parse_submissions(snapshot)
    buttons = snapshot.css("#sidebar form.subscribe-form button")
    if not any("subscribe-button--unsubscribe" in (b.get("class") or "") for b in buttons):
        yield Click(Locator.css("#sidebar form.subscribe-form button"))
    if not posts:
        raise Postcondition(f"no posts in {forum}")
    yield Goto(f"{base()}{posts[0].path}")
    return ""


def downvoted_comment_count(forum: str) -> Skill[str]:
    name = yield from forum_for(forum)
    snapshot = yield Goto(f"{base()}/f/{name}/new")
    posts = parse_submissions(snapshot)
    if not posts:
        raise Postcondition(f"no posts in {name}")
    snapshot = yield Goto(f"{base()}/user/{posts[0].submitter}/comments")
    count = 0
    for _ in range(12):
        count += sum(c.score < 0 for c in parse_comments(snapshot))
        more = [a.get("href") for a in snapshot.css("a") if "More" in a.text_content()]
        if not more:
            break
        snapshot = yield Goto(str(more[0]))
    return str(count)


def latest_post_downvotes(forum: str) -> Skill[str]:
    name = yield from forum_for(forum)
    snapshot = yield Goto(f"{base()}/f/{name}/new")
    posts = parse_submissions(snapshot)
    if not posts:
        raise Postcondition(f"no posts in {name}")
    post = posts[0]
    snapshot = yield Goto(f"{base()}{post.path}")
    count = sum(c.score < 0 and c.author != post.submitter for c in parse_comments(snapshot))
    return f"{post.submitter}; {post.title}; {count}"


def edit_bio(content: str) -> Skill[str]:
    yield Goto(f"{base()}/user/{ME}/edit_biography")
    yield from replace_text(Locator.css("textarea[name='user_biography[biography]']"), content)
    snapshot = yield Click(Locator.role("button", name="Save"))
    if content not in snapshot.html:
        raise Postcondition("biography not saved")
    return ""


def create_forum(name: str, description: str, sidebar_list: str) -> Skill[str]:
    items = re.findall(r"'([^']+)'|\"([^\"]+)\"", sidebar_list)
    sidebar = ", ".join(a or b for a, b in items) or sidebar_list.strip("[]")
    yield Goto(f"{base()}/create_forum")
    yield Type(Locator.css("input[name='forum[name]']"), name)
    yield Type(Locator.css("input[name='forum[title]']"), name)
    yield Type(Locator.css("textarea[name='forum[description]']"), description)
    yield Type(Locator.css("textarea[name='forum[sidebar]']"), sidebar)
    snapshot = yield Click(Locator.role("button", name="Create forum"))
    if f"/f/{name}" not in snapshot.url:
        raise Postcondition(f"forum not created, at {snapshot.url}")
    return ""


def post_urls(subreddit: str, num: str, order: str) -> Skill[list[str]]:
    forum = yield from forum_for(subreddit)
    snapshot = yield Goto(f"{base()}/f/{forum}/{order}")
    rows = parse_submissions(snapshot)
    if not rows:
        raise Postcondition(f"no posts listed at {snapshot.url}")
    return [f"{base()}{r.path}" for r in rows[: int(num)]]


def submit_post(forum: str, title: str, body: str = "", url: str = "") -> Skill[str]:
    yield Goto(f"{base()}/submit/{forum}")
    if url:
        yield Type(Locator.css("input[name='submission[url]']"), url)
    yield Type(Locator.css("textarea[name='submission[title]']"), title)
    if body:
        yield Type(Locator.css("textarea[name='submission[body]']"), body)
    snapshot = yield Click(Locator.role("button", name="Create submission"))
    if not re.search(rf"/f/{re.escape(forum)}/\d+/", snapshot.url, flags=re.I):
        raise Postcondition(f"submission not created, at {snapshot.url}")
    return ""


def _discussed_in(query: str) -> Skill[str]:
    # the search wants every word in one post, so each word is searched alone; my own posts are
    # left out, since an earlier attempt at the same question would count for its forum
    forums: Counter[str] = Counter()
    for word in _words(query):
        snapshot = yield Goto(f"{base()}/search?q={quote_plus(word)}")
        forums.update(r.forum for r in parse_submissions(snapshot) if r.submitter != ME)
    if not forums:
        raise Precondition(f"no forum matches or discusses {query!r}")
    return forums.most_common(1)[0][0]


def post_question(question: str, topic: str = "") -> Skill[str]:
    names = yield from forum_names()
    try:
        forum = resolve_forum(names, topic or question)
    except Precondition:
        forum = yield from _discussed_in(topic or question)
    return (yield from submit_post(forum, question, question))


def post_review(book: str, content: str) -> Skill[str]:
    return (yield from submit_post("books", book, content))


def repost_image(content: str, subreddit: str) -> Skill[str]:
    snapshot = yield Hover(Locator.css("body"))
    if "/f/pics" not in snapshot.url:
        snapshot = yield Goto(f"{base()}/f/pics")
    words = _words(content)
    posts = parse_submissions(snapshot)
    matches = [p for p in posts if all(w in p.title.lower() for w in words)] or [
        p for p in posts if any(w in p.title.lower() for w in words)
    ]
    if not matches:
        raise Precondition(f"no image of {content!r} on /f/pics")
    forum = yield from forum_for(subreddit)
    return (yield from submit_post(forum, matches[0].title, "from /f/pics", matches[0].link))


def ask_advice(issue: str, forum_phrase: str) -> Skill[str]:
    forum = yield from forum_for(forum_phrase)
    title = f"Advice about {issue}"
    return (yield from submit_post(forum, title, f"How do I {issue}? Any advice is welcome."))


def discussion(topic: str) -> Skill[str]:
    forum = yield from forum_for(topic)
    return (yield from submit_post(forum, topic, "your opinion"))


def recommendations(category: str, price: str, subreddit: str = "") -> Skill[str]:
    forum = yield from forum_for(subreddit or category)
    title = f"Recommendations for {category} within a budget of {price}"
    return (yield from submit_post(forum, title, title))


def meetup(interest: str, date: str, subreddit: str) -> Skill[str]:
    forum = yield from forum_for(subreddit)
    title = f"Virtual meetup for {interest} enthusiasts on {date}"
    return (yield from submit_post(forum, title, title))


def field_help(subreddit: str, helper: str) -> Skill[str]:
    forum = yield from forum_for(subreddit)
    title = f"What could {helper} help the {forum} field?"
    return (yield from submit_post(forum, title, title))


def _my_comment_permalink(snapshot: PageSnapshot, content: str) -> str | None:
    # the grader reads the first comment on the page, so the agent ends on the permalink of
    # the comment it wrote, where that comment comes first
    for art in snapshot.css("article.comment"):
        body = " ".join(" ".join(b.text_content().split()) for b in art.cssselect(".comment__body"))
        author = art.cssselect(".comment__info a[href^='/user/']")
        if body == content and author and author[0].text_content().strip() == ME:
            links = [
                a.get("href")
                for a in art.cssselect(".comment__nav a")
                if "/comment/" in (a.get("href") or "")
            ]
            if links:
                return str(links[0])
    return None


def _post_comment(form: str, content: str) -> Skill[str]:
    yield Type(Locator.css(f"textarea[name^='{form}']"), content)
    snapshot = yield Click(Locator.css(f"form[name^='{form}'] button").having_text("Post"))
    permalink = _my_comment_permalink(snapshot, content)
    if permalink is None:
        snapshot = yield Hover(Locator.css("body"))
        permalink = _my_comment_permalink(snapshot, content)
    if permalink is None:
        raise Postcondition("comment not posted")
    comment = permalink[permalink.index("/comment/") :]
    if not urlparse(snapshot.url).path.endswith(comment):
        yield Goto(f"{base()}{permalink}")
    return ""


def reply_to_post(content: str) -> Skill[str]:
    yield Hover(Locator.css("body"))
    return (yield from _post_comment("reply_to_submission_", content))


def reply_to_first_comment(content: str) -> Skill[str]:
    # nested replies sit in .comment__replies, so the first comment's own Reply link is the one
    # under its .comment__row; the reply form then appears inside that comment
    first = Locator.css("article.comment").nth(0)
    yield Hover(Locator.css("body"))
    yield Click(first.inside(":scope > .comment__row .comment__nav a").having_text("Reply"))
    return (yield from _post_comment("reply_to_comment_", content))


def reply_to_role(role: str, content: str) -> Skill[str]:
    m = re.match(r"(?:the|a|an)\s+(\w+)", role.strip(), flags=re.I)
    if m is None:
        raise Precondition(f"no role in {role!r}")
    noun = m.group(1).lower()
    snapshot = yield Hover(Locator.css("body"))
    says = re.compile(rf"\bI(?:'m|\u2019m| am)\s+(?:a|an|the)\s+(?:\w+\s+)?{noun}\b", re.I)
    found = [c for c in parse_comments(snapshot) if says.search(c.body)]
    if not found:
        raise Precondition(f"no comment by {role!r}")
    target = Locator.css(f"article#comment_{found[0].comment_id}")
    yield Click(target.inside(":scope > .comment__row .comment__nav a").having_text("Reply"))
    return (yield from _post_comment("reply_to_comment_", content))


def organizations_in_top(number: str, subreddit: str, topic: str) -> Skill[str]:
    forum = yield from forum_for(subreddit)
    snapshot = yield Goto(f"{base()}/f/{forum}/top")
    posts = parse_submissions(snapshot)[: int(number)]
    words = [w for w in re.findall(r"[a-z]+", topic.lower()) if len(w) > 3]
    names: list[str] = []
    for post in posts:
        domains = re.findall(r"\b[\w-]+\.(?:org|com|net|fm)\b", post.title, flags=re.I)
        if not domains:
            continue
        page = yield Goto(f"{base()}{post.path}")
        text = f"{post.title} {page.text('.submission__body') or ''}".lower()
        if sum(w[:5] in text for w in words) * 2 >= len(words):
            names += [d for d in domains if d not in names]
    return ", ".join(names) if names else "N/A"


def _my_post(post: str) -> Skill[Submission]:
    words = _words(post)
    snapshot = yield Goto(f"{base()}/search?q={quote_plus(post)}")
    found = [p for p in parse_submissions(snapshot) if p.submitter == ME]
    match = max(
        (
            p
            for p in found
            if all(w in p.title.lower().replace(" ", "") or w in p.title.lower() for w in words)
        ),
        key=lambda p: int(p.path.split("/")[3]),
        default=None,
    )
    if match is None:
        posts = yield from _user_submissions(ME)
        match = next((p for p in posts if all(w in p.title.lower() for w in words)), None)
    if match is None:
        raise Precondition(f"no post of mine titled like {post!r}")
    return match


def edit_my_post(post: str, content: str) -> Skill[str]:
    match = yield from _my_post(post)
    forum, number = match.path.split("/")[2], match.path.split("/")[3]
    yield Goto(f"{base()}/f/{forum}/{number}/-/edit")
    yield Click(Locator.css("textarea[name='submission[body]']"))
    yield Press("Control+End")
    yield Press("Enter")
    yield Type(Locator.css("textarea[name='submission[body]']"), content)
    snapshot = yield Click(Locator.role("button", name="Edit submission"))
    if content not in snapshot.html:
        raise Postcondition("edit not saved")
    return ""


REGISTRY["reddit.vote_user_submissions"] = vote_user_submissions
REGISTRY["reddit.upvote_newest"] = upvote_newest
REGISTRY["reddit.thumbs_down_top"] = thumbs_down_top
REGISTRY["reddit.subscribe_trending"] = subscribe_trending
REGISTRY["reddit.downvoted_comment_count"] = downvoted_comment_count
REGISTRY["reddit.latest_post_downvotes"] = latest_post_downvotes
REGISTRY["reddit.edit_bio"] = edit_bio
REGISTRY["reddit.create_forum"] = create_forum
REGISTRY["reddit.post_question"] = post_question
REGISTRY["reddit.post_review"] = post_review
REGISTRY["reddit.repost_image"] = repost_image
REGISTRY["reddit.ask_advice"] = ask_advice
REGISTRY["reddit.discussion"] = discussion
REGISTRY["reddit.recommendations"] = recommendations
REGISTRY["reddit.meetup"] = meetup
REGISTRY["reddit.field_help"] = field_help
REGISTRY["reddit.reply_to_post"] = reply_to_post
REGISTRY["reddit.reply_to_role"] = reply_to_role
REGISTRY["reddit.organizations_in_top"] = organizations_in_top
REGISTRY["reddit.reply_to_first_comment"] = reply_to_first_comment
REGISTRY["reddit.edit_my_post"] = edit_my_post
