from app import runtime


def _fake_clock(*values: float):
    ticks = iter(values)
    return lambda: next(ticks)


def test_run_with_status_records_elapsed_duration_on_llm_success(monkeypatch):
    monkeypatch.setattr(runtime.time, "perf_counter", _fake_clock(100.0, 100.12345))

    out = runtime.run_with_status(
        "write",
        lambda: {"report_markdown": "# ok"},
        lambda: {"report_markdown": "# fallback"},
    )

    assert out["report_markdown"] == "# ok"
    assert out["node_status"] == {
        "write": {
            "source": "llm",
            "duration_s": 0.123,
            "error": None,
        }
    }


def test_run_with_status_records_elapsed_duration_and_error_on_fallback(monkeypatch):
    monkeypatch.setattr(runtime.time, "perf_counter", _fake_clock(50.0, 50.45678))

    def _boom():
        raise TimeoutError("ollama timed out")

    out = runtime.run_with_status("write", _boom, lambda: {"report_markdown": "# fallback"})

    assert out["report_markdown"] == "# fallback"
    assert out["node_status"] == {
        "write": {
            "source": "fallback",
            "duration_s": 0.457,
            "error": "TimeoutError: ollama timed out",
        }
    }
