from __future__ import annotations

import json

from lessongen.config import Settings
from lessongen.evolve import run
from lessongen.memory import evolution_context, record_run


def _record_real_failure(db_path, index: int) -> None:
    record_run(
        {
            "run_id": f"real-run-{index}",
            "topic": f"RAG topic {index}",
            "final_status": "SHIPPED",
            "attempt_count": 2,
            "model_names": {
                "generation": "configured-generation-model",
                "judge": "configured-judge-model",
            },
            "attempts": [
                {
                    "attempt": 1,
                    "passed": False,
                    "checks": [{"check_id": "ACC-01", "passed": False}],
                    "failed_checks": [
                        {
                            "check_id": "ACC-01",
                            "reason": "The draft made an unsupported claim.",
                            "evidence": "RAG always gives a correct answer.",
                            "fix_instruction": "Support every factual claim with a source fact.",
                        }
                    ],
                },
                {
                    "attempt": 2,
                    "passed": True,
                    "checks": [{"check_id": "ACC-01", "passed": True}],
                    "failed_checks": [],
                },
            ],
        },
        path=db_path,
    )


def _mock_settings() -> Settings:
    return Settings(True, None, "https://api.openai.com/v1", "", "")


def _test_root(tmp_path) -> str:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "generator_guidelines_v1.txt").write_text(
        "- Use simple language.\n",
        encoding="utf-8",
    )
    return str(tmp_path)


def test_mock_replay_is_labeled_and_never_adopts(tmp_path) -> None:
    db = tmp_path / "memory.sqlite3"
    for index in range(3):
        _record_real_failure(db, index)
    root = _test_root(tmp_path / "project")
    report_path = tmp_path / "evolution_report.md"
    decision_log = tmp_path / "evolution.jsonl"

    decision = run(
        settings=_mock_settings(),
        db_path=db,
        root=root,
        report_path=report_path,
        decision_log_path=decision_log,
    )

    assert decision["decision"] == "REJECTED"
    assert decision["replay_mode"] == "mock"
    assert decision["real_history"]["real_run_count"] == 3
    assert decision["real_history"]["first_pass_count"] == 0
    assert decision["real_history"]["retry_count"] == 3
    assert decision["replay_before"]["first_pass_rate"] == 1
    assert decision["replay_after"]["first_pass_rate"] == 1
    assert decision["calibration_gate"]
    assert not decision["replay_gate"]
    assert (tmp_path / "project" / "prompts" / "generator_v2.txt").exists()
    assert not (
        tmp_path / "project" / "prompts" / "generator_guidelines_v2.txt"
    ).exists()
    report = report_path.read_text(encoding="utf-8")
    assert "- **Replay mode:** mock" in report
    assert "0/3 (0.0%)" in report
    assert "- Total retries: 3" in report
    assert "| Current prompt (before) | 3/3 (100.0%) | 0 | 3 |" in report
    logged = json.loads(decision_log.read_text(encoding="utf-8"))
    assert logged["decision"] == "REJECTED"


def test_mock_failure_history_does_not_meet_real_chronic_threshold(tmp_path) -> None:
    db = tmp_path / "memory.sqlite3"
    for index in range(2):
        _record_real_failure(db, index)
    mock_report = _record_data("mock-run")
    record_run(mock_report, path=db)

    history = evolution_context(min_runs=3, replay_topics=3, path=db)

    assert history["real_run_count"] == 2
    assert history["chronic_failures"] == []


def test_real_candidate_is_adopted_only_after_both_gates_pass(tmp_path, monkeypatch) -> None:
    import lessongen.evolve as evolve_module

    db = tmp_path / "memory.sqlite3"
    for index in range(3):
        _record_real_failure(db, index)
    root = _test_root(tmp_path / "project")
    replay_results = iter(
        [
            {"run_count": 3, "first_pass_count": 1, "first_pass_rate": 1 / 3, "retry_count": 3, "statuses": []},
            {"run_count": 3, "first_pass_count": 2, "first_pass_rate": 2 / 3, "retry_count": 1, "statuses": []},
        ]
    )
    calibration = {
        "mode": "mock calibration",
        "fixture_count": 12,
        "exact_matches": 12,
        "mismatches": 0,
    }
    monkeypatch.setattr(evolve_module, "_replay", lambda *_args, **_kwargs: next(replay_results))
    monkeypatch.setattr(evolve_module, "_calibration_metrics", lambda: calibration)

    decision = run(
        settings=Settings(
            False,
            "test-key",
            "https://api.openai.com/v1",
            "generator",
            "judge",
        ),
        db_path=db,
        root=root,
        report_path=tmp_path / "evolution_report.md",
        decision_log_path=tmp_path / "evolution.jsonl",
    )

    assert decision["decision"] == "ADOPTED"
    assert decision["calibration_gate"]
    assert decision["replay_gate"]
    assert decision["adopted_prompt"].endswith("generator_guidelines_v2.txt")
    assert (tmp_path / "project" / "prompts" / "generator_v2.txt").exists()
    assert (tmp_path / "project" / "prompts" / "generator_guidelines_v2.txt").exists()


def test_calibration_regression_rejects_candidate_even_if_replay_improves(
    tmp_path,
    monkeypatch,
) -> None:
    import lessongen.evolve as evolve_module

    db = tmp_path / "memory.sqlite3"
    for index in range(3):
        _record_real_failure(db, index)
    root = _test_root(tmp_path / "project")
    replay_results = iter(
        [
            {"run_count": 3, "first_pass_count": 1, "first_pass_rate": 1 / 3, "retry_count": 3, "statuses": []},
            {"run_count": 3, "first_pass_count": 3, "first_pass_rate": 1, "retry_count": 0, "statuses": []},
        ]
    )
    calibration_results = iter(
        [
            {"mode": "mock calibration", "fixture_count": 12, "exact_matches": 12, "mismatches": 0},
            {"mode": "mock calibration", "fixture_count": 12, "exact_matches": 12, "mismatches": 0},
            {"mode": "mock calibration", "fixture_count": 12, "exact_matches": 11, "mismatches": 1},
        ]
    )
    monkeypatch.setattr(evolve_module, "_replay", lambda *_args, **_kwargs: next(replay_results))
    monkeypatch.setattr(evolve_module, "_calibration_metrics", lambda: next(calibration_results))

    decision = run(
        settings=Settings(
            False,
            "test-key",
            "https://api.openai.com/v1",
            "generator",
            "judge",
        ),
        db_path=db,
        root=root,
        report_path=tmp_path / "evolution_report.md",
        decision_log_path=tmp_path / "evolution.jsonl",
    )

    assert decision["replay_gate"]
    assert not decision["calibration_gate"]
    assert decision["decision"] == "REJECTED"
    assert not (
        tmp_path / "project" / "prompts" / "generator_guidelines_v2.txt"
    ).exists()


def _record_data(run_id: str) -> dict:
    data = {
        "run_id": run_id,
        "topic": "Mock topic",
        "final_status": "ESCALATED",
        "attempt_count": 1,
        "model_names": {"generation": "mock-generation", "judge": "mock-judge"},
        "attempts": [
            {
                "attempt": 1,
                "passed": False,
                "checks": [{"check_id": "ACC-01", "passed": False}],
                "failed_checks": [
                    {
                        "check_id": "ACC-01",
                        "reason": "Mock-only reason",
                        "evidence": "Mock-only evidence",
                        "fix_instruction": "Mock-only instruction",
                    }
                ],
            }
        ],
    }
    return data
