from __future__ import annotations

from lk47.actions import Click, Goto, Hover, Locator
from lk47.sites import site_url
from lk47.skills.common import REGISTRY, Postcondition, Precondition, Skill
from lk47.skills.forms import replace_text
from lk47.skills.shopping_admin import uigrid


def show_customers() -> Skill[str]:
    yield Goto(f"{site_url('SHOPPING_ADMIN')}/customer/index/")
    return ""


def theme_preview(name: str) -> Skill[str]:
    # the theme rows carry their links in knockout handlers, not in hrefs; clicking a cell opens
    # the theme page. The name is the first cell; a child theme repeats its parent's name in
    # another cell, so the match is on the first cell only
    yield Goto(f"{site_url('SHOPPING_ADMIN')}/admin/system_design_theme/")
    snapshot = yield Click(Locator.css("tr.data-row td:first-child").having_text(name))
    if "/system_design_theme/edit/id/" not in snapshot.url:
        raise Postcondition(f"theme {name!r} did not open, at {snapshot.url}")
    return ""


def cms_page_title(old_heading: str, heading: str) -> Skill[str]:
    snapshot = yield from uigrid.open_grid("cms/page/")
    wanted = old_heading.strip().lower()
    rows = [
        r for r in uigrid.grid_rows(snapshot) if len(r.cells) > 2 and r.cells[2].lower() == wanted
    ]
    if not rows or rows[0].link_id is None:
        raise Precondition(f"no CMS page titled {old_heading!r}")
    yield Goto(f"{site_url('SHOPPING_ADMIN')}/cms/page/edit/page_id/{rows[0].link_id}/")
    yield from replace_text(Locator.css("input[name='title']"), heading)
    snapshot = yield Click(Locator.role("button", name="Save", exact=True))
    if "You saved the page" not in snapshot.html:
        snapshot = yield Hover(Locator.css("body"))
    if "You saved the page" not in snapshot.html:
        raise Postcondition(f"page not saved, landed on {snapshot.url}")
    return ""


def invoice_total(id: str) -> Skill[str]:  # noqa: A002  slot name from the template
    snapshot = yield from uigrid.open_grid("sales/invoice/")
    for row in uigrid.grid_rows(snapshot):
        if len(row.cells) >= 9 and row.cells[1].lstrip("0") == id.strip().lstrip("0"):
            return row.cells[8]
    return "N/A"


def _top_terms() -> Skill[list[tuple[str, int, int]]]:
    snapshot = yield Goto(f"{site_url('SHOPPING_ADMIN')}/admin/dashboard/")
    terms = []
    for tr in snapshot.css("#topSearchGrid_table tbody tr"):
        c = [" ".join(td.text_content().split()) for td in tr.cssselect("td")]
        if len(c) >= 3 and c[2].isdigit():
            terms.append((c[0], int(c[1]), int(c[2])))
    if not terms:
        raise Postcondition("no top search terms on the dashboard")
    return terms


def top_search_terms(n: str) -> Skill[str]:
    terms = yield from _top_terms()
    return ", ".join(t[0] for t in terms[: int(n)])


def frequent_search_brands() -> Skill[str]:
    terms = yield from _top_terms()
    brands = [t[0].split()[0].capitalize() for t in terms if t[2] >= 2]
    return ", ".join(dict.fromkeys(brands))


REGISTRY["shopping_admin.show_customers"] = show_customers
REGISTRY["shopping_admin.theme_preview"] = theme_preview
REGISTRY["shopping_admin.cms_page_title"] = cms_page_title
REGISTRY["shopping_admin.invoice_total"] = invoice_total
REGISTRY["shopping_admin.top_search_terms"] = top_search_terms
REGISTRY["shopping_admin.frequent_search_brands"] = frequent_search_brands
