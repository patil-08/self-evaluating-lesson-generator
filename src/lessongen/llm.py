"""OpenAI-compatible chat client with bounded retries and offline responses."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from lessongen.config import (
    API_MAX_RETRIES,
    API_RETRY_BASE_SECONDS,
    API_RETRY_MAX_SECONDS,
    API_TIMEOUT_SECONDS,
    Settings,
    load_config,
)

_FENCE_RE = re.compile(
    r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)

_MOCK_LESSON = """# Introduction to RAG

## What is RAG?
RAG, short for Retrieval-Augmented Generation, is a way for AI to find useful text before writing an answer. A language model is a computer program that reads text and writes an answer.

## Why does RAG matter?
A model may not know a new school notice or a private guide unless someone supplies it. RAG searches the supplied text first. This can help an answer use details from that text. The system can also show the text it found, so a person can check the answer. RAG does not train the model again for each question.

## How does RAG work?
Before a question arrives, long documents can be split into small pieces called chunks. A chunk is a small piece of a document. An embedding is a list of numbers that carries some meaning from text. A vector database stores these number lists so a system can search them.
1. Retrieve: The system finds text related to the question.
2. Augment: It adds the useful text beside the question.
3. Generate: The language model writes an answer using both.

## Example
Imagine your family keeps a local train timetable at home. You ask, “What time does the train leave?” This is only an analogy. A real RAG system uses software to search text.
1. The system searches the timetable for a line about your station.
2. It puts that line beside your question.
3. The language model writes an answer using both.
You can check the answer against the timetable. The timetable is like saved information. Finding a useful line is retrieval. Adding it beside your question is augmentation. Writing an answer is generation.

## Limitations
Search can find poor or unrelated information. RAG does not guarantee a correct answer. The model may use the found text badly. A person should check important answers.

## Mini glossary
- RAG: A way to find useful text before an AI writes an answer.
- Retrieval: Finding useful text for a question.
- Embedding: A list of numbers that carries some meaning from text.
- Vector database: A tool that stores number lists for search.
- Language model: A computer program that reads text and writes an answer.

## Recap
RAG finds useful text, adds it to a question, and asks a language model to write an answer. It can help with supplied documents, but it can still be wrong.
"""


class ModelRole(str, Enum):
    GENERATION = "generation"
    JUDGE = "judge"


class LLMError(RuntimeError):
    """Raised when a provider call fails or returns unusable data."""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


@dataclass(frozen=True)
class UsageSnapshot:
    calls: int
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def parse_json_response(content: str) -> Any:
    """Parse plain JSON, Markdown-fenced JSON, or JSON after short prose."""
    candidate = content.strip()
    match = _FENCE_RE.fullmatch(candidate)
    if match:
        candidate = match.group(1).strip()
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
        raise LLMError("The model response did not contain valid JSON.") from direct_error


class LLMClient:
    """Chat-completions wrapper with separate models and explicit telemetry."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or load_config()
        self._sleep = sleep_fn
        self._client = None
        self._client_override = client
        self._lock = threading.Lock()
        self._usage = UsageSnapshot(0, 0, 0, 0.0)
        if self.settings.mock_llm:
            return
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
        with self._lock:
            return self._usage

    def _model_for(self, role: ModelRole) -> str:
        if self.settings.mock_llm:
            return "mock-generation" if role is ModelRole.GENERATION else "mock-judge"
        if role is ModelRole.GENERATION:
            return self.settings.gen_model
        return self.settings.judge_model

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        return isinstance(
            error,
            (
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
                RateLimitError,
            ),
        ) or (
            isinstance(error, APIStatusError)
            and (error.status_code == 429 or error.status_code >= 500)
        )

    def _mock_content(self, prompt: str, role: ModelRole) -> str:
        if role is ModelRole.GENERATION:
            if prompt.startswith("Create a concise lesson outline"):
                return (
                    "1. Define RAG using the reviewed facts.\n"
                    "2. Explain its value for supplied, newer, or private documents.\n"
                    "3. Teach retrieve, augment, and generate in order.\n"
                    "4. Use a familiar school-notice example.\n"
                    "5. State limitations and recap the process."
                )
            return _MOCK_LESSON
        marker = "Evaluation input:\n"
        payload: dict[str, Any] = {}
        if marker in prompt:
            try:
                candidate = parse_json_response(prompt.rsplit(marker, 1)[1])
                if isinstance(candidate, dict):
                    payload = candidate
            except LLMError:
                payload = {}
        lesson = payload.get("lesson", "")
        checks = payload.get("hard_checks", [])
        output = []
        for check in checks if isinstance(checks, list) else []:
            if not isinstance(check, dict) or not isinstance(check.get("check_id"), str):
                continue
            check_id = check["check_id"]
            passed = True
            reason = "The deterministic mock judge found no configured obvious failure."
            evidence = ""
            if check_id == "ACC-01":
                unsupported = re.search(
                    r"(?:retrain\w* the model|"
                    r"(?<!not )guarantees? (?:a )?(?:correct|right) answer|"
                    r"cosine similarity ranks)",
                    lesson,
                    re.IGNORECASE,
                )
                if unsupported:
                    passed = False
                    evidence = unsupported.group(0)
                    reason = "This claim is unsupported or conflicts with the supplied facts."
                else:
                    reason = "The definition is consistent with the supplied RAG facts."
                    evidence = "RAG, short for Retrieval-Augmented Generation"
            elif check_id in {"L1_definition", "BEGIN-01"}:
                passed = "what is rag" in lesson.lower() and (
                    "RAG means" in lesson or "RAG, short for" in lesson
                )
                reason = "The lesson gives a plain definition." if passed else "The RAG definition is missing."
            elif check_id in {"L4_example", "EXAMPLE-03"}:
                passed = "## Example" in lesson or "## Everyday" in lesson
                evidence = "## Example" if passed else ""
                reason = "An everyday example is present." if passed else "The lesson has no everyday example."
            elif check_id in {"L7_limits", "LIMIT-01"}:
                passed = "## Limitations" in lesson or "## Limits" in lesson
                evidence = "## Limitations" if passed else ""
                reason = "A limitations section is present." if passed else "The lesson has no limitations section."
            elif check_id in {"L2_why", "COVER-02"}:
                passed = "## Why" in lesson
                evidence = "## Why" if passed else ""
                reason = "The lesson explains why RAG matters." if passed else "The why section is missing."
                if passed and check_id == "COVER-02":
                    passed = all(
                        word in lesson.lower()
                        for word in ("retrieval", "augment", "generate")
                    )
                    reason = (
                        "The lesson covers the definition, value, and three actions."
                        if passed
                        else "The explanation omits one or more RAG actions."
                    )
            elif check_id == "L3_how":
                passed = "## How" in lesson and all(word in lesson.lower() for word in ("retrieve", "augment", "generate"))
                evidence = "## How" if passed else ""
                reason = "The lesson describes the three main actions." if passed else "The process steps are incomplete."
            elif check_id in {"L6_flow", "FLOW-01"}:
                indices = [
                    lesson.find(heading)
                    for heading in (
                        "## What",
                        "## Why",
                        "## How",
                        "## Example",
                        "## Limitations",
                        "## Recap",
                    )
                ]
                passed = all(index >= 0 for index in indices) and indices == sorted(indices)
                reason = "The main ideas are introduced in teaching order." if passed else "The lesson sections are out of order."
            elif check_id == "JARG-02":
                jargon = re.search(
                    r"\b(?:cosine similarity|HNSW|BM25|non-parametric memory)\b",
                    lesson,
                    re.IGNORECASE,
                )
                passed = jargon is None
                evidence = jargon.group(0) if jargon else ""
                reason = (
                    "No configured unexplained specialized term was found."
                    if passed
                    else "A specialized term is not explained."
                )
            output.append(
                {
                    "check_id": check_id,
                    "passed": passed,
                    "reason": reason,
                    "evidence_quote": evidence,
                    "claims": (
                        [
                            {
                                "claim": "RAG combines search with answer generation.",
                                "lesson_quote": evidence,
                                "fact_ids": ["F01"],
                                "verdict": "supported",
                                "reason": "F01 supports this definition.",
                            }
                        ]
                        if check_id == "ACC-01" and passed
                        else []
                    ),
                }
            )
        return json.dumps({"checks": output})

    def complete(
        self,
        prompt: str,
        *,
        role: ModelRole = ModelRole.GENERATION,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> LLMResponse:
        model = self._model_for(role)
        started = time.perf_counter()
        if self.settings.mock_llm:
            content = self._mock_content(prompt, role)
            if role is ModelRole.JUDGE and not content:
                content = '{"checks":[]}'
            elapsed = (time.perf_counter() - started) * 1000
            response = LLMResponse(content, model, 0, 0, elapsed)
            self._record(response)
            return response

        assert self._client is not None
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        for attempt in range(API_MAX_RETRIES + 1):
            try:
                result = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs,
                )
            except Exception as error:
                if not self._is_retryable(error) or attempt >= API_MAX_RETRIES:
                    safe_message = str(error)
                    if self.settings.api_key:
                        safe_message = safe_message.replace(
                            self.settings.api_key,
                            "[REDACTED]",
                        )
                    raise LLMError(
                        f"{role.value} request failed after {attempt + 1} attempt(s): "
                        f"{safe_message}"
                    ) from error
                wait = min(
                    API_RETRY_BASE_SECONDS * (2**attempt),
                    API_RETRY_MAX_SECONDS,
                )
                self._sleep(wait)
            else:
                break
        message = result.choices[0].message.content
        if not isinstance(message, str):
            raise LLMError(f"{role.value} model returned an empty response.")
        usage = result.usage
        response = LLMResponse(
            content=message,
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        self._record(response)
        return response

    def complete_json(
        self,
        prompt: str,
        *,
        role: ModelRole = ModelRole.JUDGE,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[Any, LLMResponse]:
        response = self.complete(
            prompt,
            role=role,
            system_prompt=system_prompt,
            temperature=temperature,
            json_mode=True,
        )
        return parse_json_response(response.content), response

    def _record(self, response: LLMResponse) -> None:
        with self._lock:
            self._usage = UsageSnapshot(
                calls=self._usage.calls + 1,
                prompt_tokens=self._usage.prompt_tokens + response.prompt_tokens,
                completion_tokens=(
                    self._usage.completion_tokens + response.completion_tokens
                ),
                latency_ms=self._usage.latency_ms + response.latency_ms,
            )
