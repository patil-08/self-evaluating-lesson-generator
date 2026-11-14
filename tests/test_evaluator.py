from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.checks_llm import JudgeOutputError, evaluate_llm_checks
from src.config import Settings
from src.evaluator import evaluate_lesson
from src.llm import LLMClient, ModelRole
from src.rubric import load_rubric
from src.sources import load_facts
from tests.test_checks_code import GOOD_BEGINNER_LESSON


class FakeJudgeClient:
    def __init__(self, *, verdict: str = "supported", omit_check: str | None = None):
        self.verdict = verdict
        self.omit_check = omit_check
        self.role = None
        self.system_prompt = None

    def complete_json(self, prompt, *, role, system_prompt):
        self.role = role
        self.system_prompt = system_prompt
        assert "grounding_facts" in prompt
        checks = []
        for check in load_rubric().checks:
            if check.type != "llm" or check.id == self.omit_check:
                continue
            result = {
                "check_id": check.id,
                "passed": True,
                "reason": "The check passes based on the quoted lesson text.",
                "evidence_quote": (
                    "RAG means Retrieval-Augmented Generation, a way for a computer "
                    "to find helpful text before it writes an answer."
                ),
            }
            if check.dimension == "accurate_and_grounded":
                result["claims"] = [
                    {
                        "claim": (
                            "RAG is a way for a computer to find helpful text "
                            "before it writes an answer."
                        ),
                        "lesson_quote": (
                            "RAG means Retrieval-Augmented Generation, a way for a "
                            "computer to find helpful text before it writes an answer."
                        ),
                        "fact_ids": ["F01"],
                        "verdict": self.verdict,
                        "reason": "Compared with source fact F01.",
                    }
                ]
            checks.append(result)
        return SimpleNamespace(data={"checks": checks})


def test_llm_checks_use_judge_role_and_fail_unsupported_claims() -> None:
    client = FakeJudgeClient(verdict="unsupported")

    results = evaluate_llm_checks(
        GOOD_BEGINNER_LESSON,
        client,
        facts=load_facts(),
    )

    accuracy = next(result for result in results if result.check_id == "ACC-01")
    assert client.role.value == "judge"
    assert "strict independent lesson evaluator" in client.system_prompt
    assert not accuracy.passed
    assert "unsupported" in accuracy.reason
    assert accuracy.claims[0].fact_ids == ("F01",)


def test_llm_checks_reject_missing_check_results() -> None:
    client = FakeJudgeClient(omit_check="FLOW-01")

    with pytest.raises(JudgeOutputError, match="omitted required checks"):
        evaluate_llm_checks(
            GOOD_BEGINNER_LESSON,
            client,
            facts=load_facts(),
        )


def test_offline_mock_judge_matches_the_versioned_check_contract() -> None:
    client = LLMClient(
        Settings(
            mock_llm=True,
            api_key=None,
            base_url="https://api.openai.com/v1",
            gen_model="",
            judge_model="",
        )
    )
    lesson = client.complete("lesson", role=ModelRole.GENERATION).content

    results = evaluate_llm_checks(lesson, client, facts=load_facts())

    assert results
    assert all(result.passed for result in results)
    assert client.usage.calls == 2


def test_evaluator_records_version_and_requires_every_check_to_pass() -> None:
    client = FakeJudgeClient()

    result = evaluate_lesson(
        GOOD_BEGINNER_LESSON,
        client=client,
        facts=load_facts(),
    )

    assert result.rubric_version == "1.0"
    assert result.passed
    assert len(result.checks) == len(load_rubric().checks)
    assert all(check.passed for check in result.checks)


def test_evaluator_fails_if_any_layer_rejects_the_lesson() -> None:
    inaccurate_client = FakeJudgeClient(verdict="contradicted")

    result = evaluate_lesson(
        GOOD_BEGINNER_LESSON,
        client=inaccurate_client,
        facts=load_facts(),
    )

    assert not result.passed
    assert not next(check for check in result.checks if check.check_id == "ACC-01").passed
