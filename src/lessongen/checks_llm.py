"""Semantic checks with evidence quotes and atomic source-grounding review."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lessongen.config import JUDGE_TEMPERATURE, ROOT
from lessongen.llm import LLMClient, ModelRole
from lessongen.sources import Fact, load_facts

JUDGE_PROMPT_PATH = ROOT / "prompts" / "judge_v1.txt"
QUOTE_NORMALIZER = re.compile(r"\s+")


class JudgeOutputError(ValueError):
    """Raised when a judge response cannot be matched safely to the rubric."""


@dataclass(frozen=True)
class LLMCheckResult:
    check_id: str
    passed: bool
    reason: str
    evidence_quote: str
    claims: tuple[dict[str, Any], ...] = ()


def _quote_matches(quote: str, lesson: str) -> bool:
    normalized_lesson = QUOTE_NORMALIZER.sub(" ", lesson).casefold()
    normalized_quote = QUOTE_NORMALIZER.sub(" ", quote).strip().casefold()
    return not normalized_quote or normalized_quote in normalized_lesson


def _build_prompt(
    lesson: str,
    checks: list[dict[str, Any]],
    facts: list[Fact],
    prompt_path: str | Path | None = None,
) -> str:
    path = Path(prompt_path) if prompt_path else JUDGE_PROMPT_PATH
    template = path.read_text(encoding="utf-8")
    facts_payload = [
        {"fact_id": fact.id, "fact": fact.text, "source_url": fact.source_url}
        for fact in facts
    ]
    checks_payload = [
        {
            "check_id": item["id"],
            "dimension": item["dimension"],
            "question": item["question"],
            "pass_criteria": item["pass_criteria"],
            "fail_examples": item["fail_examples"],
        }
        for item in checks
        if item["type"] == "llm"
    ]
    return (
        template.replace("{{checks}}", json.dumps(checks_payload, ensure_ascii=False))
        .replace("{{facts}}", json.dumps(facts_payload, ensure_ascii=False))
        .replace("{{lesson}}", lesson)
        + "\n\nEvaluation input:\n"
        + json.dumps(
            {
                "lesson": lesson,
                "hard_checks": checks_payload,
                "grounding_facts": facts_payload,
            },
            ensure_ascii=False,
        )
    )


def _validate_claims(
    raw_claims: Any,
    lesson: str,
    fact_ids: set[str],
) -> tuple[tuple[dict[str, Any], ...], list[str]]:
    if not isinstance(raw_claims, list) or not raw_claims:
        return (), ["Judge returned no atomic factual claims."]
    claims = []
    errors = []
    for index, claim in enumerate(raw_claims, 1):
        if not isinstance(claim, dict):
            errors.append(f"Claim {index} is not an object.")
            continue
        text = claim.get("claim")
        quote = claim.get("lesson_quote")
        references = claim.get("fact_ids")
        verdict = claim.get("verdict")
        reason = claim.get("reason")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"Claim {index} has no text.")
            continue
        if not isinstance(quote, str) or not quote.strip() or not _quote_matches(quote, lesson):
            errors.append(f"Claim {index} has no exact lesson quote.")
            continue
        if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
            errors.append(f"Claim {index} must have a list of fact IDs.")
            continue
        if verdict not in {"supported", "unsupported", "contradicted"}:
            errors.append(f"Claim {index} has an invalid verdict.")
            continue
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"Claim {index} has no verification reason.")
            continue
        unknown = set(references) - fact_ids
        if unknown:
            errors.append(f"Claim {index} cites unknown fact IDs: {sorted(unknown)}.")
        if verdict != "supported":
            errors.append(f"Claim {index} is {verdict}: {text.strip()}")
        if verdict == "supported" and not references:
            errors.append(f"Claim {index} is supported but cites no fact IDs.")
        claims.append(
            {
                "claim": text.strip(),
                "lesson_quote": quote.strip(),
                "fact_ids": references,
                "verdict": verdict,
                "reason": reason.strip(),
            }
        )
    return tuple(claims), errors


def evaluate_llm_checks(
    lesson: str,
    client: LLMClient,
    rubric_checks: list[dict[str, Any]],
    facts: list[Fact] | None = None,
) -> list[LLMCheckResult]:
    checks = [check for check in rubric_checks if check["type"] == "llm"]
    if not checks:
        return []
    loaded_facts = facts if facts is not None else load_facts()
    known_ids = {fact.id for fact in loaded_facts}
    if len(known_ids) != len(loaded_facts):
        raise JudgeOutputError("Source facts contain duplicate IDs.")

    prompt = _build_prompt(lesson, checks, loaded_facts)
    data, _response = client.complete_json(
        prompt,
        role=ModelRole.JUDGE,
        system_prompt=(
            "Apply every hard check as a strict independent reviewer. "
            "Use only the supplied facts for accuracy and return JSON."
        ),
        temperature=JUDGE_TEMPERATURE,
    )
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise JudgeOutputError("Judge response must contain a checks array.")

    expected = {check["id"] for check in checks}
    raw_by_id = {}
    for item in data["checks"]:
        if not isinstance(item, dict):
            raise JudgeOutputError("Each judge result must be a JSON object.")
        check_id = item.get("check_id")
        if check_id not in expected or check_id in raw_by_id:
            raise JudgeOutputError(f"Unknown or duplicate judge check ID: {check_id!r}.")
        raw_by_id[check_id] = item
    missing = expected - set(raw_by_id)
    if missing:
        raise JudgeOutputError(f"Judge omitted checks: {sorted(missing)}.")

    accuracy_ids = [
        check["id"] for check in checks
        if check["dimension"] == "accurate_and_grounded"
    ]
    if len(accuracy_ids) != 1:
        raise JudgeOutputError("Rubric must define exactly one LLM accuracy check.")
    accuracy_id = accuracy_ids[0]

    results = []
    for check in checks:
        raw = raw_by_id[check["id"]]
        passed, reason, quote = raw.get("passed"), raw.get("reason"), raw.get("evidence_quote")
        if not isinstance(passed, bool):
            raise JudgeOutputError(f"{check['id']} result must include boolean passed.")
        if not isinstance(reason, str) or not reason.strip():
            raise JudgeOutputError(f"{check['id']} result must include a reason.")
        if not isinstance(quote, str) or not _quote_matches(quote, lesson):
            raise JudgeOutputError(f"{check['id']} evidence is not an exact lesson quote.")
        claims: tuple[dict[str, Any], ...] = ()
        if check["id"] == accuracy_id:
            claims, errors = _validate_claims(raw.get("claims"), lesson, known_ids)
            if errors:
                passed = False
                reason += " Atomic-claim audit failed: " + "; ".join(errors)
        results.append(
            LLMCheckResult(check["id"], passed, reason.strip(), quote.strip(), claims)
        )
    return results
