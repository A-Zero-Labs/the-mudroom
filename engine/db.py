"""Open, rebuild and write to the database."""
import sqlite3

from . import DB_PATH, ROOT

SCHEMA = ROOT / "engine" / "schema.sql"


def exists():
    return DB_PATH.exists()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rebuild():
    """Drop every table and apply the schema. Safe to run while the server is up."""
    conn = connect()
    conn.execute("PRAGMA foreign_keys = OFF")
    names = [row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    for name in names:
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, str(value)))


def log(conn, at, actor, action, target=None, reversible=True, detail=None):
    """One row per effect. Nothing here ever acts on its own, so this is the record,
    not a permission."""
    conn.execute(
        "INSERT INTO actions (at, actor, action, target, reversible, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (at, actor, action, target, int(reversible), detail),
    )
