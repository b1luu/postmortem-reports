"""End-to-end evaluation: run every curated sample through the full graph and
assert against per-sample expectations plus global quality bars.

This doubles as a benchmark: run `pytest tests/test_eval.py -s` to see per-sample
timings and a summary line.
"""

import json
import time
from pathlib import Path

import pytest

from app.graph import graph
from app.nodes.guard import REQUIRED_SECTIONS

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
SAMPLES = sorted(SAMPLES_DIR.glob("*.json"))

# Global quality bars — any regression below these fails the suite.
MAX_RUN_SECONDS = 5.0  # heuristic path is fast
MIN_ACTION_ITEMS = 3


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("sample_path", SAMPLES, ids=lambda p: p.stem)
def test_sample_end_to_end(sample_path: Path):
    sample = _load(sample_path)
    exp = sample.get("expectations", {})

    t0 = time.perf_counter()
    final = graph.invoke({"raw_input": sample["raw_input"]})
    elapsed = time.perf_counter() - t0

    # Latency bar
    assert elapsed < MAX_RUN_SECONDS, (
        f"{sample['id']} ran in {elapsed:.2f}s (> {MAX_RUN_SECONDS}s)"
    )

    # Parse correctness
    incident = final.get("incident", {})
    assert len(incident.get("events", [])) >= exp.get("min_events", 1)
    assert len(incident.get("services", [])) >= exp.get("min_services", 1)
    if exp.get("severity"):
        assert incident.get("severity") == exp["severity"], (
            f"severity mismatch on {sample['id']}: {incident.get('severity')}"
        )

    # Timeline durations computed
    durations = final.get("durations", {})
    assert durations.get("total_seconds") is not None
    assert durations.get("mttr_human")

    # Root cause content
    rc = final.get("root_cause", "").lower()
    if exp.get("expect_root_cause_substring"):
        assert exp["expect_root_cause_substring"].lower() in rc, (
            f"root cause for {sample['id']} did not mention "
            f"{exp['expect_root_cause_substring']!r}: {rc[:200]}"
        )
    assert final.get("root_cause_evidence"), "expected supporting evidence"

    # Writer output — all sections present
    report = final.get("report_markdown", "")
    for section in REQUIRED_SECTIONS:
        assert section in report, f"{sample['id']} missing section {section}"

    # Review gate
    assert final.get("review_passed") is True

    # Writer quality: at least N action items
    action_block = report.split("## Action Items", 1)[-1]
    items = [ln for ln in action_block.splitlines() if ln.startswith("- ")]
    assert len(items) >= MIN_ACTION_ITEMS, (
        f"{sample['id']} produced only {len(items)} action items"
    )

    # Print per-sample summary when -s is passed
    print(
        f"\n[eval] {sample['id']:28s} "
        f"{elapsed*1000:6.0f}ms  "
        f"events={len(incident.get('events', [])):>2}  "
        f"mttd={durations.get('mttd_human', '—'):>8}  "
        f"mttr={durations.get('mttr_human', '—'):>8}  "
        f"severity={incident.get('severity')}"
    )


def test_sample_count_nonzero():
    assert SAMPLES, "no sample fixtures found"
