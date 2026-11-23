import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import BaseModel

from pagifyx.llm.client import LLMError

MESSAGES: list[Any] = [{"role": "user", "content": "question"}]


class Answer(BaseModel):
    value: int


def run[R](awaitable: Awaitable[R]) -> R:
    async def await_it() -> R:
        return await awaitable

    return asyncio.run(await_it())


def test_complete_json_accepts_fenced_output(make_chat: Callable[..., Any]) -> None:
    chat, _ = make_chat(['```json\n{"value": 3}\n```'])
    assert run(chat.complete_json(MESSAGES, Answer)) == Answer(value=3)


def test_complete_json_retries_once_with_the_validation_error(
    make_chat: Callable[..., Any],
) -> None:
    chat, completions = make_chat(["not json", '{"value": 7}'])
    assert run(chat.complete_json(MESSAGES, Answer)).value == 7
    assert len(completions.requests) == 2
    assert "rejected" in completions.requests[1][-1]["content"]


def test_complete_json_raises_after_the_retry_also_fails(make_chat: Callable[..., Any]) -> None:
    chat, _ = make_chat(["nope", "still nope"])
    with pytest.raises(LLMError):
        run(chat.complete_json(MESSAGES, Answer))


def test_failed_check_triggers_the_retry(make_chat: Callable[..., Any]) -> None:
    chat, _ = make_chat(['{"value": 1}', '{"value": 2}'])

    def must_be_even(answer: Answer) -> None:
        if answer.value % 2:
            raise ValueError("value must be even")

    assert run(chat.complete_json(MESSAGES, Answer, check=must_be_even)).value == 2
