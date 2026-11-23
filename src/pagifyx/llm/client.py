"""OpenAI-compatible Chat Completions client that returns validated JSON.

Output is requested through the prompt and validated with pydantic. The client
does not use provider-specific response_format, so any compatible endpoint works.
"""

import logging
from collections.abc import Callable

from openai import AsyncOpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from pagifyx.core.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The model call failed or never produced valid output. The message is safe to show."""


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.removesuffix("```")
    return text.strip()


def _parse[ModelT: BaseModel](
    raw: str, schema: type[ModelT], check: Callable[[ModelT], None] | None
) -> ModelT:
    parsed = schema.model_validate_json(_strip_code_fence(raw))
    if check is not None:
        check(parsed)
    return parsed


class ChatClient:
    """Sends chat requests to one model on one OpenAI-compatible endpoint."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "ChatClient":
        client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
        )
        return cls(client, settings.llm_model)

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model, messages=messages
            )
        except OpenAIError as exc:
            raise LLMError(f"The model request failed: {exc}") from exc
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise LLMError("The model returned an empty response.")
        return content

    async def complete_json[ModelT: BaseModel](
        self,
        messages: list[ChatCompletionMessageParam],
        schema: type[ModelT],
        check: Callable[[ModelT], None] | None = None,
    ) -> ModelT:
        """Return a parsed `schema` instance. On invalid output, retry once with the error."""
        raw = await self.complete(messages)
        try:
            return _parse(raw, schema, check)
        except ValueError as exc:
            problem = str(exc)
            logger.warning("Model output rejected, retrying once: %s", problem)
        retry_messages: list[ChatCompletionMessageParam] = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    f"Your output was rejected: {problem}. "
                    "Return only the corrected JSON object, with no other text."
                ),
            },
        ]
        raw = await self.complete(retry_messages)
        try:
            return _parse(raw, schema, check)
        except ValueError as second_error:
            raise LLMError(
                f"The model did not return valid output: {second_error}"
            ) from second_error
