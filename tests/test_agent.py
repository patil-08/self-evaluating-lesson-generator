from __future__ import annotations

import json

import pytest

from src.agent import _inject_error, run_lesson
from src.cli import main
from src.config import Settings
from src.llm import LLMClient, LLMResponse, ModelRole


def _mock_settings() -> Settings:
    return Settings(
        mock_llm=True,
        api_key=None,
        base_url="https://api.openai.com/v1",
        gen_model="",
        judge_model="",
    )


@pytest.mark.parametrize(
    ("error_name", "expected_check"),
    [
        ("false_claim", "ACC-01"),
        ("jargon", "JARG-02"),
        ("no_example", "EXAMPLE-01"),
        ("bad_order", "COVER-01"),
        ("long_sentences", "BEGIN-02"),
    ],
)
def test_injected_first_draft_flaws_are_rejected(
    error_name: str,
    expected_check: str,
    tmp_path,
) -> None:
    client = LLMClient(settings=_mock_settings())

    result = run_lesson(
        "Introduction to RAG",
        client=client,
        max_retries=0,
        inject_error=error_name,
        output_dir=tmp_path,
    )

    assert result.state["status"] == "escalated_to_human"
    assert len(result.state["attempts"]) == 1
    assert expected_check in {
        check["check_id"]
        for check in result.state["rejection_log"][0]["failed_checks"]
    }


def test_graph_terminates_after_initial_attempt_and_two_retries(tmp_path) -> None:
    class AlwaysFailingClient(LLMClient):
        def complete(self, prompt, *, role=ModelRole.GENERATION, **kwargs):
            response = super().complete(prompt, role=role, **kwargs)
            if role is ModelRole.GENERATION:
                response = LLMResponse(
                    content=_inject_error(response.content, "false_claim"),
                    model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=response.latency_ms,
                )
            return response

    result = run_lesson(
        "Introduction to RAG",
        client=AlwaysFailingClient(settings=_mock_settings()),
        max_retries=2,
        output_dir=tmp_path,
    )

    assert result.state["status"] == "escalated_to_human"
    assert result.state["final_lesson"] is None
    assert len(result.state["attempts"]) == 3
    assert len(result.state["rejection_log"]) == 3
    assert result.state["rejection_log"][0]["requested_fixes"]
    assert result.state["rejection_log"][0]["changes_on_retry"]
    assert result.state["best_draft"] is not None

    report = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert report["final_status"] == "escalated_to_human"
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "Best draft — not approved" in markdown
    assert "## Passing lesson" not in markdown


def test_mock_cli_run_repairs_a_flaw_and_persists_both_reports(
    tmp_path,
    capsys,
) -> None:
    exit_code = main(
        [
            "run",
            "--topic",
            "Introduction to RAG",
            "--inject-error",
            "jargon",
            "--max-retries",
            "2",
            "--mock",
            "--output-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    reports = list(tmp_path.glob("*.json"))
    markdown_reports = list(tmp_path.glob("*.md"))
    assert exit_code == 0
    assert "Run status: passed" in captured.out
    assert "Passing lesson:" in captured.out
    assert len(reports) == len(markdown_reports) == 1

    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["final_status"] == "passed"
    assert len(report["attempts"]) == 2
    assert len(report["rejection_log"]) == 1
    assert report["rejection_log"][0]["changes_on_retry"]
    assert report["rejection_log"][0]["failed_checks"]
    assert any(
        "Cosine similarity" in text
        for text in report["rejection_log"][0]["changes_on_retry"]["removed_examples"]
    )
    assert report["models"] == {
        "generation": "mock-generation",
        "judge": "mock-judge",
    }
    assert "## Rejection log" in markdown_reports[0].read_text(encoding="utf-8")
