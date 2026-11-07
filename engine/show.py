"""What the agents read: any table, read-only, with an optional filter.

The page draws the agents reading tables. A Claude cannot open the database once every tool
that could touch it has been taken away, so this is the door left open for reading:

    python mudroom.py show                          every table with its row count
    python mudroom.py show people commitments       the rows of the tables named
    python mudroom.py show items status=staged      one table, filtered on a column
    python mudroom.py show items id=01-monday-morning-04

Columns that hold JSON come out decoded, so an item's headers and a proposal's work read as
what they are. In a house on real time, state's clock and week_start come out live, as the
engine reads them, rather than as stored at start-clean. Nothing here writes.
"""
import json

from . import clock

DECODED = {"raw": "headers", "work": "work", "detail": "detail"}


def tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def counts(conn):
    return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in tables(conn)}


def rows(conn, table, filters=None):
    """The rows of one table, in the order they were written, filtered on equal columns."""
    if table not in tables(conn):
        raise KeyError(f"No table called {table}. One of: {', '.join(tables(conn))}")
    columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    where, args = [], []
    for column, value in (filters or {}).items():
        if column not in columns:
            raise KeyError(f"{table} has no column {column}. One of: {', '.join(columns)}")
        where.append(f"{column} = ?")
        args.append(value)
    sql = f"SELECT * FROM {table}" + (" WHERE " + " AND ".join(where) if where else "")
    live = {"clock": clock.now(conn), "week_start": clock.this_week(conn).isoformat()} \
        if table == "state" and clock.real(conn) else {}
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        if d.get("key") in live:
            d["value"] = live[d["key"]]
        for column, name in DECODED.items():
            if isinstance(d.get(column), str):
                try:
                    d[name] = json.loads(d.pop(column))
                except ValueError:
                    pass
        out.append(d)
    return out
