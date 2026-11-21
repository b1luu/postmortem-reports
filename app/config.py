"""Run mode and LLM selection.

Mode and model are resolved per run, at call time: first from LangGraph's
``config["configurable"]`` (keys ``mode`` and ``llm_factory``), then from the
``POSTMORTEM_MODE`` env var, then ``DEFAULT_MODE``. Nothing is read at import.
"""

import os
from enum import Enum

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from app.llm import get_llm


class Mode(str, Enum):
    LLM = "llm"
    HEURISTIC = "heuristic"

    def __str__(self) -> str:
        return self.value


# write -> guard can loop; the attempt numbered MAX_WRITE_ATTEMPTS always uses
# the deterministic template, which has every required section.
MAX_WRITE_ATTEMPTS = 3
DEFAULT_MODE = Mode.HEURISTIC


def _configurable(config: RunnableConfig | None) -> dict:
    return (config or {}).get("configurable") or {}


def get_mode(config: RunnableConfig | None = None) -> Mode:
    value = _configurable(config).get("mode")
    if value is None or str(value).strip() == "":
        value = os.getenv("POSTMORTEM_MODE")
    if value is None or str(value).strip() == "":
        return DEFAULT_MODE
    normalized = str(value).strip().lower()
    try:
        return Mode(normalized)
    except ValueError:
        allowed = ", ".join(m.value for m in Mode)
        raise ValueError(f"invalid mode {value!r}; expected one of: {allowed}") from None


def get_chat_model(
    config: RunnableConfig | None,
    *,
    node: str,
    temperature: float,
    timeout: float,
    num_predict: int,
) -> BaseChatModel:
    factory = _configurable(config).get("llm_factory")
    if factory is not None:
        return factory(
            node=node, temperature=temperature, timeout=timeout, num_predict=num_predict
        )
    return get_llm(temperature=temperature, timeout=timeout, num_predict=num_predict)
