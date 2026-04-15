import os

from langchain_ollama import ChatOllama


def get_llm(temperature: float = 0.2, **kwargs) -> ChatOllama:
    timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "6"))
    num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "128"))
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=temperature,
        num_predict=num_predict,
        sync_client_kwargs={"timeout": timeout},
        **kwargs,
    )
