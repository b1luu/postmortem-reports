from langchain_ollama import ChatOllama

from app import llm as app_llm


def test_get_llm_uses_env_and_default_budgets(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "mistral:7b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11435")

    model = app_llm.get_llm()

    assert isinstance(model, ChatOllama)
    assert model.model == "mistral:7b"
    assert model.base_url == "http://127.0.0.1:11435"
    assert model.temperature == 0.2
    assert model.num_predict == app_llm._DEFAULT_NUM_PREDICT
    assert model.sync_client_kwargs == {"timeout": app_llm._DEFAULT_TIMEOUT}


def test_get_llm_applies_explicit_caller_budgets():
    model = app_llm.get_llm(temperature=0.5, timeout=33.0, num_predict=256)

    assert isinstance(model, ChatOllama)
    assert model.temperature == 0.5
    assert model.num_predict == 256
    assert model.sync_client_kwargs == {"timeout": 33.0}
