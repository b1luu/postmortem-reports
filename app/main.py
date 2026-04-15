import uuid
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.db import get_report, init_db, save_report
from app.graph import graph

app = FastAPI(title="Incident Postmortem Generator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class AnalyzeRequest(BaseModel):
    raw_input: str | dict[str, Any] | list[Any]


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    report_id = uuid.uuid4().hex
    final_state = graph.invoke(
        {"raw_input": req.raw_input},
        config={"run_name": f"postmortem:{report_id}"},
    )
    save_report(report_id, req.raw_input, final_state)
    return {
        "id": report_id,
        "review_passed": final_state.get("review_passed", False),
        "review_issues": final_state.get("review_issues", []),
    }


@app.get("/report/{report_id}")
def report(report_id: str) -> dict:
    row = get_report(report_id)
    if not row:
        raise HTTPException(404, "report not found")
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "report_markdown": row["report_markdown"],
        "review_passed": bool(row["review_passed"]),
    }
