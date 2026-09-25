import calendar
from datetime import date, timedelta


def add_months(d: date, months: int) -> date:
    """Shift by calendar months, clamping to the month's last day (Jan 31 + 1 → Feb 28/29)."""
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def window_start(as_of: date, *, months: int | None = None, days: int | None = None) -> date:
    """First date excluded from a trailing window ending at `as_of`.

    A card opened exactly N months before `as_of` has already aged out: this is the
    common reading of "5/24", and the cheaper mistake (telling someone to wait a day
    too long) versus the reverse.
    """
    if (months is None) == (days is None):
        raise ValueError("exactly one of months/days is required")
    return add_months(as_of, -months) if months is not None else as_of - timedelta(days=days)


def age_out_date(opened_on: date, *, months: int | None = None, days: int | None = None) -> date:
    """The date a card opened on `opened_on` stops counting toward a trailing window."""
    if (months is None) == (days is None):
        raise ValueError("exactly one of months/days is required")
    return add_months(opened_on, months) if months is not None else opened_on + timedelta(days=days)
