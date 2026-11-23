"""Shared fixtures. No test touches the network: the LLM is scripted and the browser is stubbed."""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pagifyx.core.config import Settings
from pagifyx.llm.client import ChatClient


class ScriptedCompletions:
    """Stands in for `client.chat.completions`. Returns queued replies in order."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.requests: list[list[Any]] = []

    async def create(self, *, model: str, messages: list[Any]) -> SimpleNamespace:
        assert model == "test-model"
        self.requests.append(messages)
        if not self._replies:
            raise AssertionError("The test ran out of scripted model replies.")
        content = self._replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_base_url="http://llm.test/v1",
        llm_api_key="test-key",  # type: ignore[arg-type]
        llm_model="test-model",
        output_dir=tmp_path / "output",
    )


@pytest.fixture
def make_chat() -> Callable[[list[str]], tuple[ChatClient, ScriptedCompletions]]:
    def factory(replies: list[str]) -> tuple[ChatClient, ScriptedCompletions]:
        completions = ScriptedCompletions(replies)
        fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        return ChatClient(fake_openai, "test-model"), completions  # type: ignore[arg-type]

    return factory
