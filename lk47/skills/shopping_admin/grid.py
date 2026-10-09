from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from urllib.parse import quote

from lk47.sites import site_url
from lk47.skills.common import Postcondition
from lk47.snapshot import PageSnapshot

RECORDS = re.compile(r"(\d[\d,]*) records? found")


def _token(params: Mapping[str, str]) -> str:
    # Magento encodes a grid or report filter as base64 of its query string inside the path
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return base64.b64encode(query.encode()).decode()


def report_filter_url(path: str, **params: str) -> str:
    return f"{site_url('SHOPPING_ADMIN')}/reports/{path}/filter/{_token(params)}/"


def legacy_grid_url(path: str, filters: Mapping[str, str], page: int = 1, limit: int = 200) -> str:
    # legacy grids keep the last filter in the session; an explicit filter token resets it
    return (
        f"{site_url('SHOPPING_ADMIN')}/{path}/limit/{limit}/page/{page}/filter/{_token(filters)}/"
    )


def grid_rows(snapshot: PageSnapshot) -> list[list[str]]:
    rows = []
    for tr in snapshot.css("table.data-grid tbody tr"):
        rows.append([" ".join(td.text_content().split()) for td in tr.cssselect("td")])
    return rows


def records_found(snapshot: PageSnapshot) -> int:
    for el in snapshot.css(".admin__control-support-text"):
        m = RECORDS.search(" ".join(el.text_content().split()))
        if m:
            return int(m.group(1).replace(",", ""))
    raise Postcondition(f"no record count at {snapshot.url}")
