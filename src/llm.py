"""Provider-agnostic OpenAI-compatible chat client with offline mock mode."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypeAlias

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from src.config import (
    API_MAX_RETRIES,
    API_RETRY_BASE_SECONDS,
    API_RETRY_MAX_SECONDS,
    API_TIMEOUT_SECONDS,
    Settings,
    load_config,
)

JSONValue: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None
_JSON_FENCE = re.compile(r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z", re.IGNORECASE | re.DOTALL)


class ModelRole(str, Enum):
    GENERATION = "generation"
    JUDGE = "judge"


class LLMError(RuntimeError):
    """Raised for provider failures or unusable model responses."""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class JSONLLMResponse:
    data: JSONValue
    response: LLMResponse


@dataclass(frozen=True)
class UsageSnapshot:
    calls: int
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class _UsageTotals:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


_MOCK_GENERATION = """# Introduction to RAG

## What is RAG?
RAG means Retrieval-Augmented Generation. It is a way for an AI system to find
useful information before it writes an answer. Think of it like checking your
class notes before answering a question.

## How does it work?
First, a person asks a question. Next, the system searches trusted information
for matching details. Then, it gives those details and the question to a language
model, which is an AI program that works with words. The model writes an answer
using the information it found.

For example, imagine asking a school helper, "When is the science test?" The
helper checks the school notice and uses its date to answer. RAG works in a
similar way, but a computer searches the supplied information.

## Why does RAG matter?
The system can use information supplied for a task, such as a set of company
guides. This can make answers more useful for questions about those guides.
RAG does not guarantee that every answer is correct, so important answers still
need checking."""

_MOCK_JUDGE = {
    "passed": True,
    "checks": [
        {
            "check_id": "ACC-01",
            "passed": True,
            "reason": "The lesson's factual claims match the supplied source facts.",
            "evidence_quote": "RAG means Retrieval-Augmented Generation.",
            "claims": [
                {
                    "claim": "RAG is short for Retrieval-Augmented Generation.",
                    "lesson_quote": "RAG means Retrieval-Augmented Generation.",
                    "fact_ids": ["F01"],
                    "verdict": "supported",
                    "reason": "F01 defines the name of RAG.",
                }
            ],
        },
        {
            "check_id": "BEGIN-01",
            "passed": True,
            "reason": "The prose uses direct language and explains the key idea.",
            "evidence_quote": "It is a way for an AI system to find useful information before it writes an answer.",
        },
        {
            "check_id": "EXAMPLE-03",
            "passed": True,
            "reason": "The school notice example connects searching and using found information.",
            "evidence_quote": "The helper checks the school notice and uses its date to answer.",
        },
        {
            "check_id": "JARG-02",
            "passed": True,
            "reason": "No additional unexplained technical terms appear.",
            "evidence_quote": "language model, which is an AI program that works with words.",
        },
        {
            "check_id": "COVER-02",
            "passed": True,
            "reason": "The lesson explains the definition, process, and value of RAG.",
            "evidence_quote": "The system can use information supplied for a task, such as a set of company guides.",
        },
        {
            "check_id": "FLOW-01",
            "passed": True,
            "reason": "The lesson moves from definition to process, example, and value.",
            "evidence_quote": "## What is RAG?",
        },
    ],
}


def parse_json_response(content: str) -> JSONValue:
    """Parse JSON in plain text, fenced Markdown, or a surrounding explanation."""
    candidate = content.strip()
    fence_match = _JSON_FENCE.fullmatch(candidate)
    if fence_match:
        candidate = fence_match.group(1).strip()

    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(candidate)
        return value
    except json.JSONDecodeError as direct_error:
        for index, character in enumerate(candidate):
            if character not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
                return value
            except json.JSONDecodeError:
                continue
        raise LLMError(
            "The model response did not contain valid JSON."
        ) from direct_error


class LLMClient:
    """Chat-completions wrapper with separate models and bounded API retries."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or load_config()
        self._sleep = sleep_fn
        self._usage = _UsageTotals()
        self._usage_lock = threading.Lock()

        if self.settings.mock_llm:
            self._client = None
        else:
            if not self.settings.api_key:
                raise LLMError("LLM_API_KEY is required when MOCK_LLM is disabled.")
            self._client = client or OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=API_TIMEOUT_SECONDS,
                max_retries=0,
            )

    @property
    def usage(self) -> UsageSnapshot:
        with self._usage_lock:
            return UsageSnapshot(
                calls=self._usage.calls,
                prompt_tokens=self._usage.prompt_tokens,
                completion_tokens=self._usage.completion_tokens,
                latency_ms=self._usage.latency_ms,
            )

    def _model_for(self, role: ModelRole) -> str:
        if role is ModelRole.GENERATION:
            return self.settings.gen_model if not self.settings.mock_llm else "mock-generation"
        if role is ModelRole.JUDGE:
            return self.settings.judge_model if not self.settings.mock_llm else "mock-judge"
        raise ValueError(f"Unsupported model role: {role!r}")

    @staticmethod
    def _is_retryable(error: APIError) -> bool:
        return isinstance(
            error,
            (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
        ) or (
            isinstance(error, APIStatusError)
            and (error.status_code == 429 or error.status_code >= 500)
        )

    def _mock_content(self, role: ModelRole) -> str:
        if role is ModelRole.GENERATION:
            return _MOCK_GENERATION
        if role is ModelRole.JUDGE:
            return json.dumps(_MOCK_JUDGE, sort_keys=True)
        raise ValueError(f"Unsupported model role: {role!r}")

    def complete(
        self,
        prompt: str,
        *,
        role: ModelRole = ModelRole.GENERATION,
        system_prompt: str = "You are a careful assistant.",
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Return text plus token and end-to-end latency measurements."""
        model = self._model_for(role)
        start = time.perf_counter()

        if self.settings.mock_llm:
            content = self._mock_content(role)
            response = LLMResponse(
                content=content,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            self._record(response)
            return response

        assert self._client is not None
        for retry_index in range(API_MAX_RETRIES + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                )
                message_content = completion.choices[0].message.content
                if not isinstance(message_content, str):
                    raise LLMError("The provider returned an empty or non-text response.")
                usage = completion.usage
                response = LLMResponse(
                    content=message_content,
                    model=model,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
                self._record(response)
                return response
            except APIError as error:
                if not self._is_retryable(error):
                    raise LLMError(
                        f"LLM request failed with a non-retryable provider error: {error}"
                    ) from error
                if retry_index >= API_MAX_RETRIES:
                    raise LLMError(
                        f"LLM request failed after {API_MAX_RETRIES} retries: {error}"
                    ) from error
                delay = min(
                    API_RETRY_BASE_SECONDS * (2**retry_index),
                    API_RETRY_MAX_SECONDS,
                )
                self._sleep(delay)
            except LLMError:
                raise
            except Exception as error:
                raise LLMError(f"LLM request failed unexpectedly: {error}") from error

        raise LLMError("LLM request ended without a response.")

    def complete_json(
        self,
        prompt: str,
        *,
        role: ModelRole = ModelRole.JUDGE,
        system_prompt: str = (
            "Return only valid JSON. Do not include commentary outside the JSON."
        ),
    ) -> JSONLLMResponse:
        """Request structured output and parse plain or Markdown-fenced JSON."""
        response = self.complete(
            prompt,
            role=role,
            system_prompt=system_prompt,
            temperature=0.0,
        )
        return JSONLLMResponse(
            data=parse_json_response(response.content),
            response=response,
        )

    def _record(self, response: LLMResponse) -> None:
        with self._usage_lock:
            self._usage.calls += 1
            self._usage.prompt_tokens += response.prompt_tokens
            self._usage.completion_tokens += response.completion_tokens
            self._usage.latency_ms += response.latency_ms
