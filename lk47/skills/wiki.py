from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from urllib.parse import quote

from lxml.html import HtmlElement

from lk47.actions import Goto
from lk47.sites import site_url
from lk47.skills.common import Skill
from lk47.snapshot import PageSnapshot


@dataclass(frozen=True)
class Link:
    text: str
    title: str


@dataclass(frozen=True)
class Passage:
    text: str
    links: tuple[Link, ...]
    point: tuple[float, float] | None = None


# a table as rows of cells, with every cell a row-spanning cell covers repeated in its rows
Table = tuple[tuple[Passage, ...], ...]


@dataclass(frozen=True)
class Article:
    title: str
    paragraphs: tuple[Passage, ...]
    fields: dict[str, Passage]
    headings: tuple[str, ...]
    tables: tuple[Table, ...]
    items: tuple[Passage, ...] = ()

    @property
    def lead(self) -> Passage:
        return self.paragraphs[0] if self.paragraphs else Passage("", ())

    def field(self, *labels: str) -> Passage | None:
        for label in labels:
            for name, value in self.fields.items():
                if name.lower() == label.lower():
                    return value
        return None


def root() -> str:
    # the configured address is a page of the book, ".../wikipedia_en_all_maxi_2022-05/A/<page>"
    return site_url("WIKIPEDIA").split("/A/")[0]


def _passage(element: HtmlElement) -> Passage:
    element = copy.deepcopy(element)
    point = None
    for geo in element.cssselect("span.geo"):
        m = re.match(r"\s*(-?[\d.]+);\s*(-?[\d.]+)", geo.text_content())
        if m:
            point = (float(m.group(1)), float(m.group(2)))
            break
    for br in element.iter("br"):
        br.tail = ", " + (br.tail or "")
    for extra in element.cssselect("style, .geo-inline, .geo-multi-punct, .plainlinks"):
        extra.drop_tree()
    text = " ".join(element.text_content().split())
    text = re.sub(r"\[\s*[\w\s-]{1,20}\s*\]", "", text)
    links = tuple(
        Link(" ".join(a.text_content().split()), str(a.get("title")))
        for a in element.cssselect("a[title]")
        if not str(a.get("href") or "").startswith("#")
    )
    return Passage(text, links, point)


def parse_article(snapshot: PageSnapshot) -> Article | None:
    heading = snapshot.text("h1")
    if not heading or heading == "Not Found":
        return None
    fields: dict[str, Passage] = {}
    heading_row = ""
    for row in snapshot.css("table.infobox tr"):
        th, td = row.cssselect("th"), row.cssselect("td")
        if th and td:
            label = " ".join(th[0].text_content().split()).strip("• ")
            fields.setdefault(label, _passage(td[0]))
        elif td and heading_row:
            fields.setdefault(heading_row, _passage(td[0]))
        heading_row = " ".join(th[0].text_content().split()) if th and not td else ""
    paragraphs = tuple(
        _passage(p)
        for p in snapshot.css("p")
        if p.text_content().strip() and not p.xpath("ancestor::table")
    )
    headings = tuple(" ".join(h.text_content().split()) for h in snapshot.css("h2, h3"))
    tables = tuple(_table(t) for t in snapshot.css("table.wikitable"))
    items = tuple(_passage(li) for li in snapshot.css("ul > li") if li.cssselect("a[title]"))
    return Article(heading, paragraphs, fields, headings, tables, items)


def _span(element: HtmlElement, name: str) -> int:
    return int(re.sub(r"\D", "", str(element.get(name) or "")) or 1)


def _table(table: HtmlElement) -> Table:
    rows: list[tuple[Passage, ...]] = []
    pending: dict[int, tuple[Passage, int]] = {}
    for tr in table.cssselect("tr"):
        cells = list(tr.cssselect("th, td"))
        row: list[Passage] = []
        while cells or any(c >= len(row) for c in pending):
            column = len(row)
            if column in pending:
                cell, left = pending.pop(column)
                row.append(cell)
                if left > 1:
                    pending[column] = (cell, left - 1)
            elif cells:
                element = cells.pop(0)
                cell = _passage(element)
                for _ in range(_span(element, "colspan")):
                    if _span(element, "rowspan") > 1:
                        pending[len(row)] = (cell, _span(element, "rowspan") - 1)
                    row.append(cell)
            else:
                row.append(Passage("", ()))
        rows.append(tuple(row))
    return tuple(rows)


def article(title: str) -> Skill[Article | None]:
    snapshot = yield Goto(f"{root()}/A/{quote(title.replace(' ', '_'))}")
    return parse_article(snapshot)


def search(pattern: str) -> Skill[list[str]]:
    host, book = root().rsplit("/", 1)
    snapshot = yield Goto(f"{host}/search?content={book}&pattern={quote(pattern)}")
    return [" ".join(a.text_content().split()) for a in snapshot.css(".results li > a")]
