# Postmortem

Local-first incident postmortem generator built with FastAPI, LangGraph, SQLite, and Ollama.

Paste incident text or logs into a minimal local UI, run analysis, and retrieve a structured markdown postmortem report.

## What It Does

- Accepts raw incident text through a local web UI or API
- Runs a multi-step analysis pipeline
- Produces a structured markdown postmortem
- Stores generated reports in SQLite
- Exposes job status and per-node execution metadata

## Current Product Shape

This project is intentionally local-first.

- Single-user local app
- Minimal interface at `/`
- Async analysis job flow
- Report retrieval through `/report/{id}`
- Deterministic heuristic path enabled by default for fast turnaround
- Optional Ollama-backed writer mode for richer output

## Tech Stack

- Python 3.12
- FastAPI
- Uvicorn
- LangGraph
- LangChain
- Ollama via `langchain-ollama`
- SQLite
- Pydantic
- Plain HTML, CSS, and JavaScript

## Project Structure

```text
app/
  main.py            FastAPI app and routes
  graph.py           LangGraph pipeline
  db.py              SQLite persistence
  llm.py             Ollama model client
  runtime.py         Node status helpers
  state.py           Shared graph state
  schemas.py         Structured model schemas
  nodes/
    parser.py
    root_cause.py
    factors.py
    timeline.py
    writer.py
    guard.py
  static/
    index.html       Minimal local UI
```

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Ensure Ollama is running locally with `llama3.2` available.
4. Start the FastAPI server.

Example:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 --log-level info
```

Open:

```text
http://127.0.0.1:8765/
```

## Environment Variables

Copy `.env.example` to `.env` if needed.

Important variables:

- `OLLAMA_MODEL`
- `OLLAMA_BASE_URL`
- `POSTMORTEM_DB_PATH`
- `POSTMORTEM_ENABLE_WRITER_LLM`
- `LANGSMITH_*` if you want tracing enabled

## API

### `POST /analyze`

Request:

```json
{
  "raw_input": "2026-04-14T10:01:04Z [checkout-svc] ERROR db pool exhausted"
}
```

Response:

```json
{
  "id": "report-id",
  "status": "pending"
}
```

### `GET /report/{id}`

Response fields:

- `status`
- `report_markdown`
- `review_passed`
- `node_status`
- `error`

## Example Input

```text
2026-04-14T09:58:12Z [checkout-svc] INFO deploy v412 started
2026-04-14T10:01:04Z [checkout-svc] ERROR db pool exhausted
2026-04-14T10:01:20Z [api-gateway] 503 upstream checkout-svc unavailable
2026-04-14T10:03:11Z [pagerduty] alert fired for checkout error rate
2026-04-14T10:12:45Z [checkout-svc] rollback complete
2026-04-14T10:13:10Z [api-gateway] errors back to normal
```

## Notes

- The current default path is heuristic-first for speed and reliability.
- Writer LLM usage is optional and disabled by default.
- Reports are persisted locally in SQLite.
- This is a local-first MVP, not a production incident management platform.
