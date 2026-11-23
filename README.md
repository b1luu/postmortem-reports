# Postmortem

Local-first incident postmortem generator built with FastAPI, LangGraph, SQLite, and Ollama.

Paste incident text or logs into a minimal local UI, run analysis, and retrieve a structured markdown postmortem report.

## What It Does

- Accepts raw incident text through a local web UI or API
- Runs a multi-step LangGraph analysis pipeline
- Computes MTTD, MTTR, and total incident duration from the reconstructed timeline
- Links the root cause to supporting evidence events with a confidence level
- Produces a structured markdown postmortem with per-section quality gating
- Loops back to the writer when the quality gate fails, passing the missing sections as feedback; the final attempt uses a deterministic template, so every run ends with a complete report
- Fails review (without looping) when the analysis has nothing behind it: no events extracted, or no evidence for the root cause
- Reports parse coverage so input lines are never dropped silently
- Stores generated reports in SQLite and exposes recent runs via API + UI sidebar
- Exposes per-node source (`heuristic` / `llm` / `fallback`), duration, and error
- Ships a curated sample-incident library that drives both the UI picker and the eval suite

## Current Product Shape

This project is intentionally local-first.

- Single-user local app
- Minimal interface at `/`
- Async analysis job flow
- Report retrieval through `/report/{id}`
- Deterministic heuristic path enabled by default for fast turnaround
- Optional Ollama-backed `llm` mode (`POSTMORTEM_MODE=llm`) for richer output

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
- `POSTMORTEM_MODE` — `heuristic` (default) or `llm`, read at the start of each
  run. `heuristic` never calls the LLM; input it cannot parse into timestamped
  events yields an empty incident and a `node_status.parse.error` suggesting
  `llm` mode. `llm` adds LLM extraction for such input and an
  LLM-written report (rewritten on review failure, template on the last attempt).
  A run can override it with LangGraph `config={"configurable": {"mode": ...}}`.
  Any other value makes every run fail with a `ValueError`.
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
- `node_status` — `{ parse|timeline|root_cause|factors|write|guard: { source, duration_s, error } }`
- `durations` — `{ mttd_human, mttr_human, total_human, ... }`
- `inflection_points` — `{ started, detected, resolved }` timestamps. A value is
  `null` when the input has no event supporting it (for example no alert, so no
  `detected`); nothing is guessed, and durations that depend on it are `null` too.
- `inflection_event_ids` — `{ started, detected, resolved }` event ids (`e0`, `e1`, …
  in input order, as on `incident.events`), or `null` as above
- `durations.warnings` — timing caveats, e.g. an alert logged before the first error
- `incident` — parsed events, services, severity, error signals
- `root_cause_evidence` — supporting events with timestamps and sources
- `root_cause_analysis` — trigger, symptoms, evidence ids and confidence are validated against the timeline; `reasoning` is an unverified hypothesis in `llm` mode (`{}` on older reports)
- `contributing_factor_details` — factors with category and evidence ids; factor text is an unverified hypothesis in `llm` mode (`[]` on older reports)
- `parse_coverage` — `{ lines_total, lines_parsed, lines_attached, lines_dropped, dropped_samples }`.
  Lines without a timestamp (stack frames, `Caused by:`) are attached to the event
  before them as `detail`; anything that can't be placed is counted as dropped and
  noted in the report's Impact section.
- `review_issues` — everything the review flagged (missing sections and blockers)
- `review_blockers` — analysis problems a rewrite can't fix: no events extracted, or
  a root cause with no supporting evidence. They fail the review and end the run
  without looping back to the writer.
- `error`

### `GET /api/samples`

Returns the curated sample incidents used by the UI picker and eval suite.

### `GET /api/runs?limit=20`

Returns recent runs for the UI sidebar with status, review state, and snippet.

## Tests & Evaluation

```bash
.venv/bin/python -m pytest -q            # unit + API tests
.venv/bin/python -m pytest tests/test_eval.py -s   # end-to-end eval with per-sample timings
```

The eval harness loads every JSON file in `samples/`, runs it through the full
LangGraph pipeline, and asserts per-sample expectations (severity, min events,
root-cause substring, resolution detected) plus global quality bars (latency
budget, all required sections present, minimum action items, review gate passing).

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
- LLM usage is optional; `POSTMORTEM_MODE` defaults to `heuristic`.
- Reports are persisted locally in SQLite.
- This is a local-first MVP, not a production incident management platform.
