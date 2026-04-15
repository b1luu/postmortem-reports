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
                status TEXT DEFAULT 'pending',
                raw_input TEXT,
                state_json TEXT,
                report_markdown TEXT,
                review_passed INTEGER,
                node_status TEXT,
                error TEXT
            )
            """
        )
        # Best-effort migration for databases created by an earlier schema.
        for col, defn in (
            ("status", "TEXT DEFAULT 'pending'"),
            ("node_status", "TEXT"),
            ("error", "TEXT"),
        ):
            try:
                c.execute(f"ALTER TABLE reports ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass


def _encode_raw(raw_input: Any) -> str:
    return raw_input if isinstance(raw_input, str) else json.dumps(raw_input, default=str)


def create_pending_report(report_id: str, raw_input: Any) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO reports (id, status, raw_input) VALUES (?, 'pending', ?)",
            (report_id, _encode_raw(raw_input)),
        )


def save_report(report_id: str, state: dict, status: str = "ready") -> None:
    with connect() as c:
        c.execute(
            """
            UPDATE reports SET
                status = ?,
                state_json = ?,
                report_markdown = ?,
                review_passed = ?,
                node_status = ?,
                error = NULL
            WHERE id = ?
            """,
            (
                status,
                json.dumps(state, default=str),
                state.get("report_markdown", ""),
                1 if state.get("review_passed") else 0,
                json.dumps(state.get("node_status", {}), default=str),
                report_id,
            ),
        )


def mark_failed(report_id: str, error: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE reports SET status = 'failed', error = ? WHERE id = ?",
            (error, report_id),
        )


def list_recent_reports(limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            """
            SELECT id, created_at, status, review_passed, node_status,
                   substr(report_markdown, 1, 160) AS snippet
            FROM reports
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_report(report_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return dict(row) if row else None
