"""Load the hard rubric and combine deterministic and semantic evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lessongen.checks_code import evaluate_code_checks
from lessongen.checks_llm import evaluate_llm_checks
from lessongen.llm import LLMClient
from lessongen.sources import Fact, load_facts

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUBRIC_PATH = ROOT / "rubric" / "rubric_v1.yaml"


class RubricError(ValueError):
    """Raised when the hard-rubric file is invalid."""


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


def load_rubric(path: str | Path | None = None) -> dict[str, Any]:
    rubric_path = Path(path) if path else DEFAULT_RUBRIC_PATH
    try:
        data = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RubricError(f"Cannot load rubric {rubric_path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise RubricError("Rubric must have a string version.")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise RubricError("Rubric must have a non-empty checks list.")
    seen = set()
    for check in checks:
        if not isinstance(check, dict):
            raise RubricError("Every rubric check must be a mapping.")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip() or check_id in seen:
            raise RubricError(f"Rubric check ID is missing or duplicated: {check_id!r}.")
        if check.get("type") not in {"code", "llm"} or check.get("severity") != "hard":
            raise RubricError(f"{check_id} must be a hard code or llm check.")
        for required in ("dimension", "question", "pass_criteria", "fail_examples"):
            if not check.get(required):
                raise RubricError(f"{check_id} is missing {required}.")
        if not isinstance(check["fail_examples"], list):
            raise RubricError(f"{check_id} fail_examples must be a list.")
        seen.add(check_id)
    if sum(check["type"] == "llm" and check["dimension"] == "accurate_and_grounded" for check in checks) != 1:
        raise RubricError("Rubric needs exactly one LLM accuracy-and-grounding check.")
    return data


def evaluate_lesson(
    lesson: str,
    *,
    client: LLMClient,
    facts: list[Fact] | None = None,
    rubric_path: str | Path | None = None,
) -> EvaluationResult:
    rubric = load_rubric(rubric_path)
    active_facts = facts if facts is not None else load_facts()
    code = evaluate_code_checks(lesson, rubric["checks"])
    semantic = evaluate_llm_checks(lesson, client, rubric["checks"], active_facts)
    results = {
        item.check_id: ("code", item.passed, item.reason, item.evidence_quote)
        for item in code
    }
    for item in semantic:
        if item.check_id in results:
            raise RubricError(f"Duplicate evaluated check {item.check_id}.")
        results[item.check_id] = ("llm", item.passed, item.reason, item.evidence_quote)
    expected = {check["id"] for check in rubric["checks"]}
    if set(results) != expected:
        raise RubricError(
            f"Evaluator result does not cover rubric exactly; "
            f"missing={sorted(expected - set(results))}, "
            f"unexpected={sorted(set(results) - expected)}."
        )
    checks = tuple(
        EvaluationCheck(
            check_id=check["id"],
            dimension=check["dimension"],
            check_type=results[check["id"]][0],
            passed=results[check["id"]][1],
            reason=results[check["id"]][2],
            evidence_quote=results[check["id"]][3],
        )
        for check in rubric["checks"]
    )
    return EvaluationResult(rubric["version"], all(item.passed for item in checks), checks)
