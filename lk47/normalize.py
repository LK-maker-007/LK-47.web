from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9


class Unsupported(ValueError):
    pass


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def admin_dates(self) -> tuple[str, str]:
        # Magento admin date inputs take M/D/YYYY without zero padding
        return f"{self.start.month}/{self.start.day}/{self.start.year}", (
            f"{self.end.month}/{self.end.day}/{self.end.year}"
        )

    def short_dates(self) -> tuple[str, str]:
        # the report filter re-renders dates as M/d/yy once a report is shown
        return short_date(self.start), short_date(self.end)


def short_date(d: date) -> str:
    return f"{d.month}/{d.day}/{d.year % 100:02d}"


def _month_range(year: int, month: int) -> DateRange:
    return DateRange(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))


def _month(word: str) -> int:
    try:
        return MONTHS[word.lower().rstrip(".")]
    except KeyError:
        raise Unsupported(word) from None


def period_range(text: str) -> DateRange:
    s = text.strip()
    s = re.sub(r"^(?:in|during|durning|on)\s+", "", s, flags=re.I)
    if m := re.fullmatch(r"(\d{4})", s):
        y = int(m.group(1))
        return DateRange(date(y, 1, 1), date(y, 12, 31))
    if m := re.fullmatch(r"([A-Za-z]+\.?)\s+(\d{4})", s):
        return _month_range(int(m.group(2)), _month(m.group(1)))
    if m := re.fullmatch(r"(\d{4})/(\d{1,2})", s):
        return _month_range(int(m.group(1)), int(m.group(2)))
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", s):
        return _month_range(int(m.group(2)), int(m.group(1)))
    if m := re.fullmatch(r"Q(?:uarter)?\s*([1-4])\s+(\d{4})", s, flags=re.I):
        q, y = int(m.group(1)), int(m.group(2))
        first = 3 * (q - 1) + 1
        return DateRange(date(y, first, 1), _month_range(y, first + 2).end)
    raise Unsupported(text)


def parse_day(text: str) -> date:
    s = text.strip()
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    if m := re.fullmatch(r"([A-Za-z]+\.?)\s+(\d{1,2}),?\s+(\d{4})", s):
        return date(int(m.group(3)), _month(m.group(1)), int(m.group(2)))
    if m := re.fullmatch(r"(?:the\s+)?(beginning|start|end)\s+of\s+(.+)", s, flags=re.I):
        span = period_range(m.group(2))
        return span.end if m.group(1).lower() == "end" else span.start
    raise Unsupported(text)


def relative_range(today: date, text: str) -> DateRange:
    s = re.sub(r"^(?:for|over|in|during)\s+", "", text.strip(), flags=re.I).lower()
    if s == "last month":
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return _month_range(year, month)
    if s == "this month":
        return _month_range(today.year, today.month)
    if m := re.fullmatch(r"(?:the\s+)?last\s+(\d+)\s+days", s):
        return DateRange(today - timedelta(days=int(m.group(1))), today)
    if s == "last year":
        return DateRange(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    if s == "this year":
        return DateRange(date(today.year, 1, 1), date(today.year, 12, 31))
    if m := re.fullmatch(r"q(?:uarter)?\s*([1-4])", s):
        return period_range(f"Q{m.group(1)} {today.year}")
    raise Unsupported(text)
