import pytest

from app.config import DEFAULT_MODE, Mode, get_mode


def test_configurable_beats_env(monkeypatch):
    monkeypatch.setenv("POSTMORTEM_MODE", "heuristic")
    assert get_mode({"configurable": {"mode": "LLM "}}) is Mode.LLM


def test_env_beats_default(monkeypatch):
    monkeypatch.setenv("POSTMORTEM_MODE", "llm")
    assert get_mode() is Mode.LLM
    assert get_mode({"configurable": {}}) is Mode.LLM


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("POSTMORTEM_MODE", raising=False)
    assert get_mode() is DEFAULT_MODE is Mode.HEURISTIC


def test_invalid_mode_raises(monkeypatch):
    with pytest.raises(ValueError, match="turbo"):
        get_mode({"configurable": {"mode": "turbo"}})
    monkeypatch.setenv("POSTMORTEM_MODE", "fast")
    with pytest.raises(ValueError, match="fast"):
        get_mode()
