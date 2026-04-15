import os

from langchain_ollama import ChatOllama

_DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "15"))
_DEFAULT_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))


def get_llm(
    temperature: float = 0.2,
    timeout: float | None = None,
    num_predict: int | None = None,
    **kwargs,
) -> ChatOllama:
    """Build a ChatOllama with per-call timeout and output-length budgets.

    Callers should pass explicit `timeout` and `num_predict` tuned to the node's
    workload. Env vars provide a safe floor for anything that doesn't override.
    """
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=temperature,
        num_predict=num_predict if num_predict is not None else _DEFAULT_NUM_PREDICT,
        sync_client_kwargs={
            "timeout": timeout if timeout is not None else _DEFAULT_TIMEOUT
        },
        **kwargs,
    )
