from __future__ import annotations

import sqlite3

from lessongen.memory import (
    add_note,
    failure_history,
    failure_patterns,
    get_generation_lessons,
    record_run,
)


def _report(run_id: str = "run-1") -> dict:
    return {
        "run_id": run_id,
        "topic": "Introduction to RAG",
        "final_status": "SHIPPED",
        "attempt_count": 2,
        "attempts": [
            {
                "attempt": 1,
                "checks": [
                    {"check_id": "ACC-01", "passed": False},
                    {"check_id": "COVER-01", "passed": True},
                ],
                "failed_checks": [
                    {
                        "check_id": "ACC-01",
                        "reason": "A claim was unsupported.",
                        "evidence": "retrains the model",
                        "fix_instruction": "Remove claims that are absent from sources.",
                    }
                ],
            },
            {
                "attempt": 2,
                "checks": [
                    {"check_id": "ACC-01", "passed": True},
                    {"check_id": "COVER-01", "passed": True},
                ],
                "failed_checks": [],
            },
        ],
    }


def test_memory_tracks_failure_reason_effective_fix_and_feedback_note(tmp_path) -> None:
    db = tmp_path / "memory.sqlite3"
    record_run(_report(), path=db)
    add_note("run-1", "Please include a familiar school example.", path=db)

    patterns = failure_patterns(path=db)
    assert patterns == [
        {
            "check_id": "ACC-01",
            "run_count": 1,
            "failure_count": 1,
            "example_reason": "A claim was unsupported.",
            "example_fix_instruction": "Remove claims that are absent from sources.",
            "resolved_count": 1,
            "unresolved_count": 0,
        }
    ]
    history = failure_history(path=db)
    assert history[0]["resolved"] == 1
    assert history[0]["resolved_by_attempt"] == 2
    assert history[0]["fix_instruction"] == "Remove claims that are absent from sources."

    lessons = get_generation_lessons(path=db)
    assert any("immediate retry/retries passed" in item["text"] for item in lessons)
    assert any("school example" in item["text"] for item in lessons)


def test_old_failure_table_is_migrated_without_losing_rows(tmp_path) -> None:
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE failed_checks (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                attempt INTEGER NOT NULL,
                check_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence TEXT NOT NULL,
                PRIMARY KEY (run_id, attempt, check_id)
            );
            INSERT INTO runs (run_id, topic, status, attempt_count, report_json)
            VALUES ('old-run', 'RAG', 'ESCALATED', 1, '{}');
            INSERT INTO failed_checks
            (run_id, attempt, check_id, reason, evidence)
            VALUES ('old-run', 1, 'ACC-01', 'Old failure reason', 'old evidence');
            """
        )

    assert failure_patterns(path=db)[0]["example_reason"] == "Old failure reason"
    details = failure_history(path=db)
    assert details[0]["reason"] == "Old failure reason"
    assert details[0]["fix_instruction"] == ""
    assert details[0]["resolved"] is None
