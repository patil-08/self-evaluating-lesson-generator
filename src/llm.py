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
RAG means Retrieval-Augmented Generation, a way for a computer to search useful
text before it writes an answer. It uses a language model, an AI program that
reads and writes words, to form the answer. The chosen notes can give the model
details it may not already have.

## How does RAG work?
First, a person asks a question. Next, the system searches its saved notes.
Long pages can be split into small pieces called chunks. An embedding is a list
of numbers that carries some meaning from a piece of text. A vector database is
a tool that stores these number patterns and can find close matches.
The system finds text that may help with the question. It gives that text and
the question to the language model. Then the model writes an answer using the
text it found.

## Everyday worked example
Think about a student who needs the date of a science exam. The student has a
school notice with the date. RAG works in a similar way, but a computer searches
the supplied notes.
First, the student asks, "When is the science exam?"
Next, the helper finds the school notice with the date.
Then, the helper uses that date to answer the question.
Finally, the student can check the notice.
The notice is like the saved information. Finding the right line is retrieval.
Giving that line to the helper adds context. Writing the date is generation.
This example shows the main steps without using a computer term for each one.

## Why does RAG matter?
A model may not have access to a private guide or a recent change. RAG can
search information supplied for a task before the model answers. This can make
an answer more useful for questions about those notes. A system can show the
source text with its answer. Then a person can check where the detail came from.

## Mini glossary
- **RAG**: A way to search information before an AI writes an answer.
- **Retrieval**: Finding useful text for a question.
- **Embedding**: A list of numbers that carries some meaning from text.
- **Vector database**: A tool that stores number patterns for search.
- **Language model**: An AI program that reads and writes words.

## Limits
RAG does not guarantee a correct answer. The search may find the wrong text.
The model can still be wrong, so important answers need checking."""

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

    def _mock_judge_content(self, prompt: str) -> str:
        marker = "Evaluation input:\n"
        if marker not in prompt:
            return json.dumps(_MOCK_JUDGE, sort_keys=True)

        payload = json.loads(prompt.rsplit(marker, 1)[1])
        lesson = payload.get("lesson")
        requested_checks = payload.get("hard_checks")
        if not isinstance(lesson, str) or not isinstance(requested_checks, list):
            raise LLMError("Mock judge received an invalid evaluation payload.")

        plain_text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+.*$", " ", lesson)
        plain_text = re.sub(r"\s+", " ", plain_text).strip()
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", plain_text)
            if part.strip()
        ]
        words = lambda text: re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?", text)
        headings = [
            heading.lower()
            for heading in re.findall(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", lesson)
        ]
        section_index = {
            "what": next((i for i, h in enumerate(headings) if "what is rag" in h or "what rag is" in h), None),
            "how": next((i for i, h in enumerate(headings) if "how" in h and "rag" in h), None),
            "example": next((i for i, h in enumerate(headings) if "example" in h), None),
            "why": next((i for i, h in enumerate(headings) if "why" in h and "rag" in h), None),
        }
        false_claim = next(
            (
                sentence
                for sentence in sentences
                if re.search(
                    r"\b(?:rag\s+)?(?:guarantees?|always\s+(?:gives|makes|produces|returns)\s+(?:a\s+)?(?:correct|right))\b",
                    sentence,
                    re.IGNORECASE,
                )
                and not re.search(
                    r"\b(?:does not|doesn't|never)\s+guarantees?\b",
                    sentence,
                    re.IGNORECASE,
                )
            ),
            None,
        )
        unsupported_claim = next(
            (
                sentence
                for sentence in sentences
                if re.search(r"\bcosine similarity\b", sentence, re.IGNORECASE)
            ),
            None,
        )
        definition_quote = next(
            (
                sentence
                for sentence in sentences
                if re.search(r"\bRAG\s+means\s+Retrieval-Augmented Generation\b", sentence, re.IGNORECASE)
            ),
            sentences[0] if sentences else "",
        )
        idiom_present = any(
            phrase in lesson.lower()
            for phrase in ("in a nutshell", "piece of cake", "hit the ground running")
        )
        long_sentence = next(
            (sentence for sentence in sentences if len(words(sentence)) > 30),
            None,
        )
        section_order_valid = (
            all(section_index[name] is not None for name in ("what", "how", "example", "why"))
            and section_index["what"] < section_index["how"]
            < section_index["example"] < section_index["why"]
        )
        all_required_sections = all(
            section_index[name] is not None for name in ("what", "how", "why")
        )
        unknown_jargon = next(
            (
                sentence
                for sentence in sentences
                if re.search(r"\bcosine similarity\b|\bnon-parametric memory\b", sentence, re.IGNORECASE)
                and not re.search(
                    r"\b(?:means|is a|is an|refers to|called)\b",
                    sentence,
                    re.IGNORECASE,
                )
            ),
            None,
        )
        idiom_quote = next(
            (
                sentence
                for sentence in sentences
                if any(
                    phrase in sentence.lower()
                    for phrase in ("in a nutshell", "piece of cake", "hit the ground running")
                )
            ),
            None,
        )
        example_quote = next(
            (
                sentence
                for sentence in sentences
                if any(word in sentence.lower() for word in ("school", "library", "cricket", "shop"))
            ),
            "",
        )

        output_checks: list[dict[str, Any]] = []
        for requested in requested_checks:
            check_id = requested.get("check_id")
            dimension = requested.get("dimension")
            passed = True
            evidence = definition_quote
            reason = "The deterministic mock judge found no configured obvious failure."
            claims: list[dict[str, Any]] | None = None

            if dimension == "accurate_and_grounded":
                claim_quote = false_claim or unsupported_claim or definition_quote
                if false_claim:
                    passed = False
                    reason = "The lesson claims RAG guarantees correctness, contrary to fact F13."
                    claims = [{
                        "claim": false_claim,
                        "lesson_quote": false_claim,
                        "fact_ids": ["F13"],
                        "verdict": "contradicted",
                        "reason": "F13 states that RAG does not guarantee a correct answer.",
                    }]
                elif unsupported_claim:
                    passed = False
                    reason = "The lesson makes an unsupported claim about cosine similarity."
                    claims = [{
                        "claim": unsupported_claim,
                        "lesson_quote": unsupported_claim,
                        "fact_ids": [],
                        "verdict": "unsupported",
                        "reason": "No supplied fact supports this claim.",
                    }]
                else:
                    reason = "A representative definition claim matches source fact F01."
                    claims = [{
                        "claim": "RAG combines information search with answer generation.",
                        "lesson_quote": claim_quote,
                        "fact_ids": ["F01"],
                        "verdict": "supported",
                        "reason": "Fact F01 describes search combined with a language model answer.",
                    }]
                evidence = claim_quote
            elif dimension == "beginner_friendly_language":
                if check_id == "BEGIN-01" and (long_sentence or idiom_present):
                    passed = False
                    evidence = long_sentence or idiom_quote or ""
                    reason = "A long sentence or idiom makes the text harder for a beginner."
            elif dimension == "teaches_by_example":
                if check_id == "EXAMPLE-03":
                    passed = section_index["example"] is not None
                    evidence = example_quote if passed else ""
                    reason = (
                        "The lesson includes a familiar example."
                        if passed
                        else "The lesson has no example section."
                    )
            elif dimension == "no_unexplained_jargon":
                if check_id == "JARG-02" and unknown_jargon:
                    passed = False
                    evidence = unknown_jargon
                    reason = "The specialized term is not explained in the same sentence."
            elif dimension == "covers_key_points":
                if check_id == "COVER-02" and not all_required_sections:
                    passed = False
                    evidence = ""
                    reason = "At least one required what/how/why section is missing."
            elif dimension == "coherent_teaching_flow":
                if not section_order_valid:
                    passed = False
                    evidence = ""
                    reason = "The definition, process, example, and value sections are missing or out of order."

            item: dict[str, Any] = {
                "check_id": check_id,
                "passed": passed,
                "reason": reason,
                "evidence_quote": evidence,
            }
            if claims is not None:
                item["claims"] = claims
            output_checks.append(item)
        return json.dumps(
            {"passed": all(item["passed"] for item in output_checks), "checks": output_checks},
            sort_keys=True,
        )

    def _mock_content(self, role: ModelRole, prompt: str) -> str:
        if role is ModelRole.GENERATION:
            return _MOCK_GENERATION
        if role is ModelRole.JUDGE:
            return self._mock_judge_content(prompt)
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
            content = self._mock_content(role, prompt)
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
