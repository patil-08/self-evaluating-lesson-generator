from __future__ import annotations

from lessongen.checks_code import evaluate_code_checks
from lessongen.evaluator import load_rubric


def _check(lesson: str, check_id: str):
    rubric_check = next(
        check for check in load_rubric()["checks"] if check["id"] == check_id
    )
    return evaluate_code_checks(lesson, [rubric_check])[0]


def test_active_rubric_order_is_enforced() -> None:
    correct_order = "## What is RAG?\n## Why does RAG matter?\n## How does RAG work?"
    wrong_order = "## What is RAG?\n## How does RAG work?\n## Why does RAG matter?"

    assert _check(correct_order, "COVER-01").passed
    assert not _check(wrong_order, "COVER-01").passed


def test_lesson_length_uses_the_active_rubric_parameters() -> None:
    lesson = "word " * 300

    assert _check(lesson, "LENGTH-01").passed
    assert not _check("word " * 299, "LENGTH-01").passed
    assert not _check("word " * 751, "LENGTH-01").passed
