from __future__ import annotations

from lessongen.config import Settings
from lessongen.evaluator import evaluate_lesson
from lessongen.llm import LLMClient


def _mock_client() -> LLMClient:
    return LLMClient(
        settings=Settings(
            mock_llm=True,
            api_key=None,
            base_url="https://api.openai.com/v1",
            gen_model="",
            judge_model="",
        )
    )


def test_mock_lesson_passes_every_hard_check() -> None:
    client = _mock_client()
    lesson = client.complete("Generate a lesson").content

    result = evaluate_lesson(lesson, client=client)

    assert result.passed
    assert all(check.passed for check in result.checks)


def test_mock_judge_rejects_an_unsupported_guarantee() -> None:
    client = _mock_client()
    lesson = client.complete("Generate a lesson").content.replace(
        "RAG does not guarantee a correct answer.",
        "RAG guarantees a correct answer.",
    )

    result = evaluate_lesson(lesson, client=client)

    accuracy = next(check for check in result.checks if check.check_id == "ACC-01")
    assert not result.passed
    assert not accuracy.passed
    assert "guarantees a correct answer" in accuracy.evidence_quote
