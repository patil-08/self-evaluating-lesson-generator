from __future__ import annotations

from src.evolution import (
    CHRONIC_FAILURE_MIN_RUNS,
    ReplayMetrics,
    _adoption_allowed,
    _create_candidate,
    run_evolution,
)
from src.config import Settings
from src.memory import MemoryStore
from src.prompt_registry import PromptSpec, get_active_prompt


def _failure_run(
    run_id: str,
    *,
    mock: bool,
    repeat_failure: bool = True,
) -> dict:
    check = {
        "check_id": "JARG-01",
        "dimension": "no_unexplained_jargon",
        "reason": "A term was used before a plain-language definition.",
        "fix_instruction": "Define each term at first use.",
    }
    attempt_count = 2 if repeat_failure else 1
    attempts = [
        {
            "attempt": index,
            "all_checks": [{"check_id": "JARG-01", "passed": False}],
        }
        for index in range(1, attempt_count + 1)
    ]
    return {
        "run_id": run_id,
        "topic": "Introduction to RAG",
        "status": "escalated_to_human",
        "attempts": attempts,
        "rejection_log": [
            {
                "attempt": attempt["attempt"],
                "failed_checks": [check],
                "requested_fixes": [],
            }
            for attempt in attempts
        ],
        "prompt_version": "1.0",
        "rubric_version": "1.0",
        "model_names": {
            "generation": "mock-generation" if mock else "writer-live",
            "judge": "mock-judge" if mock else "judge-live",
        },
        "memory_influenced": False,
    }


def _mock_settings() -> Settings:
    return Settings(
        mock_llm=True,
        api_key=None,
        base_url="https://api.openai.com/v1",
        gen_model="",
        judge_model="",
    )


def test_chronic_threshold_counts_distinct_real_runs_not_attempts(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    for run_number in range(CHRONIC_FAILURE_MIN_RUNS - 1):
        memory.record_run(_failure_run(f"real-{run_number}", mock=False))
    memory.record_run(_failure_run("mock-run", mock=True))
    old_rubric_run = _failure_run("old-rubric", mock=False)
    old_rubric_run["rubric_version"] = "0.9"
    memory.record_run(old_rubric_run)

    before_threshold = memory.evolution_snapshot(
        "1.0",
        chronic_run_threshold=CHRONIC_FAILURE_MIN_RUNS,
    )
    memory.record_run(_failure_run("real-final", mock=False))
    at_threshold = memory.evolution_snapshot(
        "1.0",
        chronic_run_threshold=CHRONIC_FAILURE_MIN_RUNS,
    )

    assert before_threshold["chronic_failures"] == []
    assert before_threshold["real_run_count"] == CHRONIC_FAILURE_MIN_RUNS - 1
    assert at_threshold["chronic_failures"][0]["distinct_run_count"] == (
        CHRONIC_FAILURE_MIN_RUNS
    )


def test_adoption_requires_calibration_and_strict_first_pass_improvement() -> None:
    baseline = ReplayMetrics("1.0", run_count=3, first_pass_count=1, retry_count=4)
    unchanged = ReplayMetrics("2.0", run_count=3, first_pass_count=1, retry_count=1)
    improved = ReplayMetrics("2.0", run_count=3, first_pass_count=2, retry_count=2)

    assert not _adoption_allowed(
        calibration_not_worse=True,
        baseline=baseline,
        candidate=unchanged,
    )
    assert not _adoption_allowed(
        calibration_not_worse=False,
        baseline=baseline,
        candidate=improved,
    )
    assert _adoption_allowed(
        calibration_not_worse=True,
        baseline=baseline,
        candidate=improved,
    )


def test_candidate_creation_uses_next_unused_file_without_overwrite(
    tmp_path,
    monkeypatch,
) -> None:
    import src.evolution as evolution

    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    base_path = prompt_dir / "generator_v1.txt"
    base_path.write_text("Baseline lesson prompt.", encoding="utf-8")
    old_v2 = prompt_dir / "generator_v2.txt"
    old_v2.write_text("Preserve this earlier candidate.", encoding="utf-8")
    monkeypatch.setattr(evolution, "PROMPTS_DIR", prompt_dir)
    active = PromptSpec(version="1.0", path=base_path)

    candidate = _create_candidate(
        active,
        [
            {
                "check_id": "JARG-01",
                "dimension": "no_unexplained_jargon",
            }
        ],
        [
            {
                "check_id": "JARG-01",
                "fix_instruction": "Define terms at first use.",
            }
        ],
    )

    assert candidate.version == "3.0"
    assert candidate.path.name == "generator_v3.txt"
    assert old_v2.read_text(encoding="utf-8") == "Preserve this earlier candidate."
    assert "Define terms at first use." in candidate.path.read_text(encoding="utf-8")


def test_evolve_report_separates_mock_history_and_does_not_promote_it(
    tmp_path,
) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.record_run(_failure_run("mock-only", mock=True))
    report_path = tmp_path / "evolution_report.md"
    changelog_path = tmp_path / "CHANGELOG.md"

    result = run_evolution(
        memory,
        _mock_settings(),
        report_path=report_path,
        changelog_path=changelog_path,
    )

    report = report_path.read_text(encoding="utf-8")
    changelog = changelog_path.read_text(encoding="utf-8")
    assert result.adopted is False
    assert result.candidate_path is None
    assert "No hard check reached the chronic-failure threshold" in report
    assert "Mock (not real)" in report
    assert "no live run history" in report
    assert "Candidate: not created." in changelog
    assert get_active_prompt().version == "1.0"


def test_real_chronic_failures_create_but_do_not_adopt_without_live_settings(
    tmp_path,
    monkeypatch,
) -> None:
    import src.evolution as evolution

    memory = MemoryStore(tmp_path / "memory.sqlite3")
    for index, topic in enumerate(
        ("Introduction to RAG", "RAG for school notes", "RAG for support teams")
    ):
        run = _failure_run(f"real-{index}", mock=False, repeat_failure=False)
        run["topic"] = topic
        memory.record_run(run)

    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    base_path = prompt_dir / "generator_v1.txt"
    base_path.write_text("Baseline lesson prompt.", encoding="utf-8")
    active = PromptSpec(version="1.0", path=base_path)
    monkeypatch.setattr(evolution, "PROMPTS_DIR", prompt_dir)
    monkeypatch.setattr(evolution, "get_active_prompt", lambda: active)

    result = run_evolution(
        memory,
        _mock_settings(),
        report_path=tmp_path / "evolution_report.md",
        changelog_path=tmp_path / "CHANGELOG.md",
    )

    assert result.candidate_path == prompt_dir / "generator_v2.txt"
    assert result.candidate_path.is_file()
    assert result.adopted is False
    assert "not adopted" in result.decision
