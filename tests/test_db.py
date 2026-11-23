import json

from app import db


def _use_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "postmortems.db"))
    db.init_db()


def test_create_pending_report_persists_string_and_structured_raw_input(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)

    db.create_pending_report("str-run", "2026-04-14T10:00:00Z [svc] ERROR boom")
    structured = {"severity": "sev2", "events": [{"event": "ERROR boom"}]}
    db.create_pending_report("dict-run", structured)

    str_row = db.get_report("str-run")
    dict_row = db.get_report("dict-run")

    assert str_row is not None
    assert str_row["status"] == "pending"
    assert str_row["raw_input"] == "2026-04-14T10:00:00Z [svc] ERROR boom"

    assert dict_row is not None
    assert dict_row["status"] == "pending"
    assert json.loads(dict_row["raw_input"]) == structured


def test_save_report_persists_review_passed_boolean_flags(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)

    db.create_pending_report("pass-run", "raw")
    db.save_report("pass-run", {"report_markdown": "# ok", "review_passed": True})

    db.create_pending_report("fail-run", "raw")
    db.save_report("fail-run", {"report_markdown": "# bad", "review_passed": False})

    db.create_pending_report("missing-run", "raw")
    db.save_report("missing-run", {"report_markdown": "# old"})

    assert db.get_report("pass-run")["review_passed"] == 1
    assert db.get_report("fail-run")["review_passed"] == 0
    assert db.get_report("missing-run")["review_passed"] == 0


def test_mark_failed_and_list_recent_reports_limit(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)

    for idx in range(3):
        db.create_pending_report(f"run-{idx}", f"raw-{idx}")
    db.mark_failed("run-1", "RuntimeError: upstream timeout")

    failed = db.get_report("run-1")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error"] == "RuntimeError: upstream timeout"

    recent = db.list_recent_reports(limit=2)
    assert len(recent) == 2
    assert db.get_report("does-not-exist") is None
