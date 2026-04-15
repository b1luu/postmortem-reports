import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.db import (
    create_pending_report,
    get_report,
    init_db,
    mark_failed,
    save_report,
)
from app.graph import graph

app = FastAPI(title="Incident Postmortem Generator")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("postmortem.api")
STATIC_DIR = Path(__file__).with_name("static")
INDEX_HTML = STATIC_DIR / "index.html"


class AnalyzeRequest(BaseModel):
    raw_input: str | dict[str, Any] | list[Any]


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML)


def _run_analysis(report_id: str, raw_input: Any) -> None:
    try:
        final_state = graph.invoke(
            {"raw_input": raw_input},
            config={"run_name": f"postmortem:{report_id}"},
        )
        save_report(report_id, final_state, status="ready")
        logger.info(
            "analyze_complete id=%s review_passed=%s node_status=%s",
            report_id,
            final_state.get("review_passed"),
            final_state.get("node_status", {}),
        )
    except Exception as exc:
        logger.exception("analyze_failed id=%s", report_id)
        mark_failed(report_id, f"{type(exc).__name__}: {exc}")


@app.post("/analyze", status_code=202)
def analyze(req: AnalyzeRequest, background: BackgroundTasks) -> dict:
    report_id = uuid.uuid4().hex
    create_pending_report(report_id, req.raw_input)
    background.add_task(_run_analysis, report_id, req.raw_input)
    return {"id": report_id, "status": "pending"}


@app.get("/report/{report_id}")
def report(report_id: str) -> dict:
    row = get_report(report_id)
    if not row:
        raise HTTPException(404, "report not found")

    node_status_raw = row.get("node_status")
    try:
        node_status = json.loads(node_status_raw) if node_status_raw else {}
    except (TypeError, ValueError):
        node_status = {}

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status": row.get("status") or "ready",
        "review_passed": bool(row.get("review_passed")),
        "report_markdown": row.get("report_markdown") or "",
        "node_status": node_status,
        "error": row.get("error"),
    }
