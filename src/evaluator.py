"""Combine deterministic and semantic checks into one versioned hard decision."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.checks_code import evaluate_code_checks
from src.checks_llm import evaluate_llm_checks
from src.llm import LLMClient
from src.rubric import Rubric, load_rubric
from src.sources import Fact, load_facts


@dataclass(frozen=True)
class EvaluationCheck:
    check_id: str
    dimension: str
    check_type: str
    passed: bool
    reason: str
    evidence_quote: str


@dataclass(frozen=True)
class EvaluationResult:
    rubric_version: str
    passed: bool
    checks: tuple[EvaluationCheck, ...]


def evaluate_lesson(
    lesson: str,
    *,
    client: LLMClient | None = None,
    facts: list[Fact] | None = None,
    rubric_path: str | Path | None = None,
) -> EvaluationResult:
    """Evaluate every rubric item; pass only when every hard check passes."""
    rubric: Rubric = load_rubric(rubric_path)
    active_facts = facts if facts is not None else load_facts()
    llm_client = client if client is not None else LLMClient()

    code_results = evaluate_code_checks(lesson, rubric)
    llm_results = evaluate_llm_checks(
        lesson,
        llm_client,
        rubric,
        active_facts,
    )
    result_by_id: dict[str, tuple[str, bool, str, str]] = {}
    for result in code_results:
        result_by_id[result.check_id] = (
            "code",
            result.passed,
            result.reason,
            result.evidence_quote,
        )
    for result in llm_results:
        if result.check_id in result_by_id:
            raise ValueError(f"Duplicate evaluated rubric check ID: {result.check_id}.")
        result_by_id[result.check_id] = (
            "llm",
            result.passed,
            result.reason,
            result.evidence_quote,
        )

    expected_ids = {check.id for check in rubric.checks}
    actual_ids = set(result_by_id)
    if expected_ids != actual_ids:
        missing = sorted(expected_ids - actual_ids)
        unexpected = sorted(actual_ids - expected_ids)
        raise ValueError(
            "Evaluation result does not cover the loaded rubric exactly "
            f"(missing={missing}, unexpected={unexpected})."
        )

    checks = tuple(
        EvaluationCheck(
            check_id=check.id,
            dimension=check.dimension,
            check_type=check.type,
            passed=result_by_id[check.id][1],
            reason=result_by_id[check.id][2],
            evidence_quote=result_by_id[check.id][3],
        )
        for check in rubric.checks
    )
    return EvaluationResult(
        rubric_version=rubric.version,
        passed=all(check.passed for check in checks),
        checks=checks,
    )
