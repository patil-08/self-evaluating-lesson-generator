from __future__ import annotations

from pathlib import Path

import pytest

from lessongen.checks_code import evaluate_code_checks
from lessongen.evaluator import RubricError, load_rubric


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rubric():
    return load_rubric(ROOT / "rubric" / "rubric_v1.yaml")


def _result(lesson: str, rubric, check_id: str):
    result = evaluate_code_checks(lesson, rubric["checks"])
    return next(item for item in result if item.check_id == check_id)


def test_rubric_has_only_hard_checks_and_unique_ids(rubric) -> None:
    checks = rubric["checks"]
    assert all(check["severity"] == "hard" for check in checks)
    assert len({check["id"] for check in checks}) == len(checks)


def test_section_order_rejects_wrong_order(rubric) -> None:
    lesson = "## How does RAG work?\nSteps.\n## What is RAG?\nDefinition.\n## Why does RAG matter?\nValue."
    result = _result(lesson, rubric, "COVER-01")
    assert not result.passed
    assert "order" in result.reason


def test_length_check_accepts_a_lesson_within_range(rubric) -> None:
    lesson = " ".join(["RAG finds useful text before an AI answers."] * 45)
    result = _result(lesson, rubric, "LENGTH-01")
    assert result.passed


@pytest.mark.parametrize(
    ("lesson", "check_id"),
    [
        ("## Example\nA short school example.", "EXAMPLE-01"),
        ("## Limitations\nEverything is always correct.", "LIMIT-01"),
        ("## Mini glossary\n- RAG: Helpful.\n", "GLOSS-01"),
    ],
)
def test_missing_example_limits_or_glossary_fails(rubric, lesson, check_id) -> None:
    result = _result(lesson, rubric, check_id)
    assert not result.passed


def test_invalid_rubric_fails_clearly(tmp_path: Path) -> None:
    bad_rubric = tmp_path / "bad.yaml"
    bad_rubric.write_text("version: 1\nchecks: []\n", encoding="utf-8")

    with pytest.raises(RubricError, match="string version"):
        load_rubric(bad_rubric)
