"""Test doubles for chat models.

langchain's FakeListChatModel raises NotImplementedError from
with_structured_output, so nodes that ask for structured output need this.
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig, RunnableLambda
from pydantic import Field


class FakeStructuredModel(BaseChatModel):
    """Scripted chat model for both `prompt | fake` and structured output.

    Items in either queue may be exceptions, which are raised when popped.
    """

    text_responses: list[Any] = Field(default_factory=list)
    structured_responses: dict[str, list[Any]] = Field(default_factory=dict)
    calls: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-structured"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        metadata = run_manager.metadata if run_manager else {}
        self.calls.append(
            {
                "kind": "text",
                "schema": None,
                "input": str(messages),
                "metadata": {k: metadata.get(k) for k in ("mode", "node")},
            }
        )
        if not self.text_responses:
            raise AssertionError("FakeStructuredModel: no text responses left")
        item = self.text_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=item))])

    def with_structured_output(self, schema, **kwargs):
        name = schema.__name__

        # Must be named `config` and annotated for RunnableLambda to inject it.
        def _respond(prompt_input, config: RunnableConfig):
            metadata = config.get("metadata") or {}
            self.calls.append(
                {
                    "kind": "structured",
                    "schema": name,
                    "input": str(prompt_input),
                    "metadata": {k: metadata.get(k) for k in ("mode", "node")},
                }
            )
            queue = self.structured_responses.get(name) or []
            if not queue:
                raise AssertionError(f"FakeStructuredModel: no {name} responses left")
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            assert isinstance(item, schema), f"expected {name}, got {type(item).__name__}"
            return item

        return RunnableLambda(_respond)


class ForbidLLM:
    """llm_factory that records the requesting node and refuses to build a model."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, **kw) -> BaseChatModel:
        self.calls.append(str(kw.get("node", "?")))
        raise RuntimeError(f"LLM called: {kw.get('node')}")
