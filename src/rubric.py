"""Load and validate the versioned binary lesson-evaluation rubric."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

RubricCheckType = Literal["code", "llm"]
_DEFAULT_RUBRIC_PATH = Path(__file__).resolve().parents[1] / "rubric" / "v1.yaml"


class RubricError(ValueError):
    """Raised when a rubric is missing or violates its hard-check schema."""


@dataclass(frozen=True)
class RubricCheck:
    id: str
    dimension: str
    type: RubricCheckType
    question: str
    pass_criteria: str
    fail_examples: tuple[str, ...]
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Rubric:
    version: str
    checks: tuple[RubricCheck, ...]


def load_rubric(path: str | Path | None = None) -> Rubric:
    """Load a rubric only when every check is an explicit hard binary decision."""
    rubric_path = Path(path) if path is not None else _DEFAULT_RUBRIC_PATH
    try:
        raw = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RubricError(f"Rubric file was not found: {rubric_path}") from error
    except OSError as error:
        raise RubricError(f"Could not read rubric file {rubric_path}: {error}") from error
    except yaml.YAMLError as error:
        raise RubricError(f"Rubric file is invalid YAML: {error}") from error

    if not isinstance(raw, dict):
        raise RubricError("Rubric root must be a YAML mapping.")
    version = raw.get("version")
    raw_checks = raw.get("checks")
    if not isinstance(version, str) or not version.strip():
        raise RubricError("Rubric must have a non-empty version.")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise RubricError("Rubric must contain a non-empty checks list.")

    checks: list[RubricCheck] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_checks):
        label = f"Rubric check {index + 1}"
        if not isinstance(item, dict):
            raise RubricError(f"{label} must be a YAML mapping.")

        check_id = item.get("id")
        dimension = item.get("dimension")
        check_type = item.get("type")
        question = item.get("question")
        pass_criteria = item.get("pass_criteria")
        fail_examples = item.get("fail_examples")
        parameters = item.get("parameters", {})

        if not isinstance(check_id, str) or not check_id.strip():
            raise RubricError(f"{label} must have a non-empty id.")
        if check_id in seen_ids:
            raise RubricError(f"Duplicate rubric check ID: {check_id}.")
        if item.get("severity") != "hard":
            raise RubricError(f"{check_id} must have severity: hard; advisory checks are forbidden.")
        if check_type not in {"code", "llm"}:
            raise RubricError(f"{check_id} type must be 'code' or 'llm'.")
        if not isinstance(dimension, str) or not dimension.strip():
            raise RubricError(f"{check_id} must name an evaluation dimension.")
        if not isinstance(question, str) or not question.strip():
            raise RubricError(f"{check_id} must have a precise yes/no question.")
        if not isinstance(pass_criteria, str) or not pass_criteria.strip():
            raise RubricError(f"{check_id} must state explicit pass criteria.")
        if not isinstance(fail_examples, list) or not fail_examples:
            raise RubricError(f"{check_id} must include at least one fail example.")
        if not all(isinstance(example, str) and example.strip() for example in fail_examples):
            raise RubricError(f"{check_id} fail_examples must be non-empty strings.")
        if not isinstance(parameters, dict):
            raise RubricError(f"{check_id} parameters must be a YAML mapping.")

        seen_ids.add(check_id)
        checks.append(
            RubricCheck(
                id=check_id,
                dimension=dimension,
                type=check_type,
                question=question.strip(),
                pass_criteria=pass_criteria.strip(),
                fail_examples=tuple(example.strip() for example in fail_examples),
                parameters=parameters,
            )
        )

    return Rubric(version=version.strip(), checks=tuple(checks))
