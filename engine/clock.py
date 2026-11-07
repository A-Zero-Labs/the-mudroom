"""The engine's own clock. Dates in the world are relative to Monday; reset stamps them."""
from datetime import date, datetime, timedelta

from . import db

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def real(conn):
    """Whether the house runs on real time: start-clean sets this, the demo never does."""
    return db.get_state(conn, "clock_mode", "demo") == "real"


def now(conn):
    """The engine's now: its own clock while the demo plays, the real clock otherwise. Read
    the time through here, never from the state table: in a real house the stored clock is
    only the moment start-clean ran."""
    if not real(conn):
        return db.get_state(conn, "clock")
    return datetime.now().isoformat(timespec="minutes")


def this_week(conn):
    """Monday of the engine's week: the demo's own week while it plays, the real one otherwise.
    In the demo a weekday in a judgement, 'Thursday 12:00', means that day of this week; in a
    real house it means the coming one, which resolve works out from today."""
    if not real(conn):
        return as_date(db.get_state(conn, "week_start"))
    return week_start()


def slot_label(dt):
    """'Monday morning', 'Monday midday', 'Monday end of day', from when items were staged."""
    part = "morning" if dt.hour < 12 else "midday" if dt.hour < 15 else "end of day"
    return f"{DAYS[dt.weekday()]} {part}"


def week_start(today=None):
    """Monday of the week that holds today (the real today unless one is given)."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def stamp(start, day, time=None):
    """Turn a day offset from Monday, and an optional HH:MM, into an ISO string."""
    d = start + timedelta(days=day)
    if time is None:
        return d.isoformat()
    hours, minutes = time.split(":")
    return datetime(d.year, d.month, d.day, int(hours), int(minutes)).isoformat(timespec="minutes")


def resolve(text, start, need_time=False, onward=None):
    """A date or time as the handover file may write it: ISO as in the database, or a
    weekday with an optional time, meaning that day of the week that starts at start. With
    onward, a date, the weekday is the first such day from then on instead: in a house on
    real time, 'Thursday' said on a Saturday means the coming one."""
    text = str(text).strip()
    value = _iso(text)
    if value is None:
        if onward is not None:
            start = onward - timedelta(days=onward.weekday())
            if (named := _weekday(text, start)) is not None and as_date(named) < onward:
                start += timedelta(days=7)
        value = _weekday(text, start)
    if value is None:
        raise ValueError(f"{text!r} is not a date: write 2026-09-16, 2026-09-16T09:00, "
                         "Wednesday or Wednesday 09:00")
    if need_time and "T" not in value:
        raise ValueError(f"{text!r} needs a time")
    return value


def _iso(text):
    try:
        if "T" in text:
            return datetime.fromisoformat(text).isoformat(timespec="minutes")
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _weekday(text, start):
    parts = text.split()
    if not parts or len(parts) > 2 or parts[0].capitalize() not in DAYS:
        return None
    day = DAYS.index(parts[0].capitalize())
    if len(parts) == 1:
        return stamp(start, day)
    hours, sep, minutes = parts[1].partition(":")
    if not (sep and hours.isdigit() and minutes.isdigit() and int(hours) < 24 and int(minutes) < 60):
        return None
    return stamp(start, day, parts[1])


def add_minutes(iso, minutes):
    return (datetime.fromisoformat(iso) + timedelta(minutes=minutes)).isoformat(timespec="minutes")


def as_datetime(text):
    return datetime.fromisoformat(text)


def as_date(text):
    return date.fromisoformat(text[:10])


def day_name(d):
    return DAYS[d.weekday()]


def clock_label(dt):
    """'Monday 08:00'"""
    return f"{DAYS[dt.weekday()]} {dt:%H:%M}"


def long_date(d):
    """'14 September 2026'"""
    return f"{d.day} {d:%B %Y}"


def short_date(d):
    """'Mon 14 Sep'"""
    return f"{DAYS[d.weekday()][:3]} {d.day} {d:%b}"


def near(d):
    """Whether a date is close enough to today that its weekday alone says which day it is.
    The demo's week always is; a real house's log and diary run over months."""
    return abs((d - date.today()).days) <= 6
