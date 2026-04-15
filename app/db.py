import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any

DB_PATH = os.getenv("POSTMORTEM_DB_PATH", "./postmortems.db")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                raw_input TEXT,
                state_json TEXT,
                report_markdown TEXT,
                review_passed INTEGER
            )
            """
        )


def save_report(report_id: str, raw_input: Any, state: dict) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO reports (id, raw_input, state_json, report_markdown, review_passed) VALUES (?, ?, ?, ?, ?)",
            (
                report_id,
                json.dumps(raw_input) if not isinstance(raw_input, str) else raw_input,
                json.dumps(state, default=str),
                state.get("report_markdown", ""),
                1 if state.get("review_passed") else 0,
            ),
        )


def get_report(report_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return dict(row) if row else None
