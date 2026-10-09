from __future__ import annotations

from lk47.actions import Hover, Locator
from lk47.skills.common import REGISTRY, Precondition, Skill
from lk47.skills.gitlab.common import base, find_project, search_project
from lk47.skills.gitlab.read import _project_of
from lk47.skills.gitlab.write import create_file, edit_file, new_project, project_description
from lk47.skills.knowledge import topics
from lk47.skills.reddit.forums import forum_for, post_urls, submit_post
from lk47.skills.shopping.cart import review_titles

# a code repository with no forum of its own is posted to the deep learning forum
REPOSITORY_FORUM = "deeplearning"


def urls_file(directory: str, gitlab_repo: str, subreddit: str) -> Skill[str]:
    try:
        urls = yield from post_urls(subreddit, "5", "new")
    except Precondition:
        return "N/A"
    project = yield from find_project(gitlab_repo)
    yield from create_file(project, f"{directory}/urls.txt", urls)
    return ""


def readme_repo(name: str, num: str) -> Skill[str]:
    urls = yield from post_urls("DIY", num, "active")
    yield from new_project(name)
    snapshot = yield Hover(Locator.css("body"))
    yield from edit_file(_project_of(snapshot.url), "README.md", urls)
    return ""


def review_feedback_post(product: str, rating: str) -> Skill[str]:
    titles = yield from review_titles(product, rating)
    if not titles:
        raise Precondition(f"no reviews of {product!r} at {rating}")
    forum = yield from forum_for("games")
    return (yield from submit_post(forum, f"real user feedback on {product}", "; ".join(titles)))


def repo_post(topic: str) -> Skill[str]:
    project = yield from search_project(topic)
    url = f"{base()}{project}"
    try:
        forum = yield from forum_for(topic)
    except Precondition:
        forum = yield from forum_for(REPOSITORY_FORUM)
    title = f"GitLab repository related to {topic}: {project.split('/')[-1]}"
    return (yield from submit_post(forum, title, url, url))


def promote_repo(repo: str, subreddit: str) -> Skill[str]:
    project = yield from find_project(repo)
    description = yield from project_description(project)
    forum = yield from forum_for(subreddit)
    return (yield from submit_post(forum, description, "", f"{base()}{project}"))


def wiki_readme(name: str, subject: str) -> Skill[str]:
    found = yield from topics(subject)
    yield from new_project(name)
    snapshot = yield Hover(Locator.css("body"))
    yield from edit_file(_project_of(snapshot.url), "README.md", ["; ".join(found)])
    return ""


REGISTRY["cross.urls_file"] = urls_file
REGISTRY["cross.readme_repo"] = readme_repo
REGISTRY["cross.review_feedback_post"] = review_feedback_post
REGISTRY["cross.repo_post"] = repo_post
REGISTRY["cross.promote_repo"] = promote_repo
REGISTRY["cross.wiki_readme"] = wiki_readme
