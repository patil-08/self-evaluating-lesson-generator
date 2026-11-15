from __future__ import annotations

import json

import pytest

from lessongen.cli import main
from lessongen.config import Settings
from lessongen.evaluator import EvaluationCheck, EvaluationResult
from lessongen.graph import build
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


def test_retry_cap_escalates_without_shipping_a_failing_lesson() -> None:
    evaluations = 0

    def always_fail(*_args, **_kwargs) -> EvaluationResult:
        nonlocal evaluations
        evaluations += 1
        return EvaluationResult(
            rubric_version="test-rubric",
            passed=False,
            checks=(
                EvaluationCheck(
                    check_id="ACC-01",
                    dimension="accurate_and_grounded",
                    check_type="llm",
                    passed=False,
                    reason="The claim is unsupported.",
                    evidence_quote="an unsupported claim",
                ),
            ),
        )

    workflow = build(
        client=_mock_client(),
        max_retries=2,
        evaluator_fn=always_fail,
    )

    result = workflow.invoke({"topic": "Introduction to RAG"})

    assert evaluations == 3
    assert result["attempt_count"] == 3
    assert len(result["attempt_results"]) == 3
    assert result["status"] == "ESCALATED"
    assert "best_draft" in result
    assert "lesson" not in result
    assert all(not attempt["passed"] for attempt in result["attempt_results"])
    assert result["feedback"][0]["evidence"] == "an unsupported claim"
    assert result["feedback"][0]["fix_instruction"]


@pytest.mark.parametrize(
    ("injection", "failed_check"),
    [
        ("false_claim", "ACC-01"),
        ("jargon", "JARG-02"),
        ("no_example", "EXAMPLE-01"),
        ("bad_order", "COVER-01"),
        ("long_sentences", "BEGIN-02"),
    ],
)
def test_mock_injections_are_rejected_then_repaired(injection, failed_check) -> None:
    result = build(
        client=_mock_client(),
        max_retries=1,
        inject_error=injection,
    ).invoke({"topic": "Introduction to RAG"})

    assert result["status"] == "SHIPPED"
    assert result["attempt_count"] == 2
    assert failed_check in {
        item["check_id"] for item in result["attempt_results"][0]["failed_checks"]
    }


def test_full_mock_run_repairs_and_writes_both_rejection_logs(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LESSONGEN_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    output = tmp_path / "lesson-output"

    exit_code = main(
        [
            "run",
            "--topic",
            "Introduction to RAG",
            "--inject-error",
            "false_claim",
            "--max-retries",
            "1",
            "--mock",
            "--out",
            str(output),
        ]
    )

    assert exit_code == 0
    assert "Status: SHIPPED after 2 attempt(s)." in capsys.readouterr().out
    report = json.loads((output / "rejection_log.json").read_text(encoding="utf-8"))
    assert report["final_status"] == "SHIPPED"
    assert report["attempt_count"] == 2
    assert report["attempts"][0]["failed_checks"]
    assert any(
        failure["check_id"] == "ACC-01"
        for failure in report["attempts"][0]["failed_checks"]
    )
    assert report["attempts"][1]["passed"]
    assert report["attempts"][1]["changes_from_previous"] != "Initial draft."
    assert report["rubric_version"]
    assert report["prompt_versions"]["generator"]
    assert report["model_names"] == {
        "generation": "mock-generation",
        "judge": "mock-judge",
    }
    assert set(report["usage"]) >= {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
    }
    assert (output / "lesson.md").is_file()
    assert (output / "rejection_log.md").is_file()
    assert not (output / "best_draft.md").exists()


def test_feedback_memory_and_evolve_subcommands(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LESSONGEN_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    output = tmp_path / "lesson-output"
    assert main(
        [
            "run",
            "--mock",
            "--topic",
            "RAG",
            "--inject-error",
            "false_claim",
            "--max-retries",
            "1",
            "--out",
            str(output),
        ]
    ) == 0
    report = json.loads((output / "rejection_log.json").read_text(encoding="utf-8"))

    assert main(
        [
            "feedback",
            "--run",
            report["run_id"],
            "--note",
            "Clear example",
        ]
    ) == 0
    assert "Feedback note saved" in capsys.readouterr().out
    assert main(["memory"]) == 0
    memory_output = capsys.readouterr().out
    assert "SHIPPED" in memory_output
    assert "Clear example" in memory_output
    assert "resolved by attempt 2" in memory_output

    next_output = tmp_path / "next-run"
    assert main(
        [
            "run",
            "--mock",
            "--topic",
            "RAG follow-up",
            "--out",
            str(next_output),
        ]
    ) == 0
    next_report = json.loads(
        (next_output / "rejection_log.json").read_text(encoding="utf-8")
    )
    assert next_report["generation_memory"][0]["influenced"]
    assert any(
        "Clear example" in lesson["text"]
        for lesson in next_report["generation_memory"][0]["lessons"]
    )
    assert any(
        "Check ACC-01" in lesson["text"]
        and "pass only when every claim is supported" in lesson["text"]
        for lesson in next_report["generation_memory"][0]["lessons"]
    )
    assert "**Attempt 1 memory:** influenced" in (
        next_output / "rejection_log.md"
    ).read_text(encoding="utf-8")
    assert main(
        [
            "evolve",
            "--mock",
            "--report",
            str(tmp_path / "evolution_report.md"),
            "--decision-log",
            str(tmp_path / "evolution.jsonl"),
        ]
    ) == 0
    evolve_output = capsys.readouterr().out
    assert "Evolution: INELIGIBLE" in evolve_output
    assert "Calibration gate: **NOT RUN**" in (
        tmp_path / "evolution_report.md"
    ).read_text(encoding="utf-8")
