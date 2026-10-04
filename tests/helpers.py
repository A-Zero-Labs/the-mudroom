"""Shared setup for the engine tests: a throwaway database from the schema and the tests' own
seed and cast, with the tests' own batch brought in through the same intake a source skill
uses. Nothing here reads the demo's files, so the suite still runs once the demo has left."""
from pathlib import Path

import batch as SOURCE
from engine import clock, db, intake, seed

HERE = Path(__file__).resolve().parent
START = clock.as_date("2026-09-14")  # a Monday; the tests stamp their week to it
BATCH = HERE / "rounds" / "01-test-morning.md"
SEED = HERE / "seed.json"


def stage(tmp):
    """Point the engine at a database under tmp, reset it, bring the test batch in, and return
    an open connection. The caller restores db.DB_PATH afterwards."""
    db.DB_PATH = tmp / "test.db"
    seed.reset(today=START, path=SEED)
    conn = db.connect()
    intake.register(conn, SOURCE.handoff(BATCH, START))
    return conn
