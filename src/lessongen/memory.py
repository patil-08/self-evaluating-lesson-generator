"""SQLite run history, rejection patterns, and learner feedback."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from lessongen.config import ROOT

DEFAULT_DB_PATH = ROOT / "data" / "memory.sqlite3"


def database_path() -> Path:
    return Path(os.getenv("LESSONGEN_MEMORY_DB", DEFAULT_DB_PATH))


def _connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS failed_checks (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            attempt INTEGER NOT NULL,
            check_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence TEXT NOT NULL,
            fix_instruction TEXT NOT NULL DEFAULT '',
            resolved INTEGER,
            resolved_by_attempt INTEGER,
            PRIMARY KEY (run_id, attempt, check_id)
        );
        CREATE TABLE IF NOT EXISTS feedback_notes (
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(failed_checks)")
    }
    for column, definition in (
        ("fix_instruction", "TEXT NOT NULL DEFAULT ''"),
        ("resolved", "INTEGER"),
        ("resolved_by_attempt", "INTEGER"),
    ):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE failed_checks ADD COLUMN {column} {definition}"
            )
    return connection


def record_run(report: dict[str, Any], *, path: str | Path | None = None) -> str:
    """Persist only report metadata and failed-check evidence, not lesson drafts."""
    run_id = str(report["run_id"])
    with _connect(path) as connection:
        connection.execute(
            "INSERT INTO runs (run_id, topic, status, attempt_count, report_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                report["topic"],
                report["final_status"],
                report["attempt_count"],
                json.dumps(report, ensure_ascii=False),
            ),
        )
        attempts = report["attempts"]
        for index, attempt in enumerate(attempts):
            next_check_results = (
                {
                    check["check_id"]: check["passed"]
                    for check in attempts[index + 1]["checks"]
                }
                if index + 1 < len(attempts)
                else {}
            )
            for failure in attempt["failed_checks"]:
                resolved = next_check_results.get(failure["check_id"])
                resolved_by_attempt = (
                    attempts[index + 1]["attempt"] if resolved is True else None
                )
                connection.execute(
                    "INSERT INTO failed_checks "
                    "(run_id, attempt, check_id, reason, evidence, fix_instruction, "
                    "resolved, resolved_by_attempt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        attempt["attempt"],
                        failure["check_id"],
                        failure["reason"],
                        failure["evidence"],
                        failure.get("fix_instruction", ""),
                        int(resolved) if resolved is not None else None,
                        resolved_by_attempt,
                    ),
                )
    return run_id


def list_runs(*, limit: int = 20, path: str | Path | None = None) -> list[dict[str, Any]]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT run_id, topic, status, attempt_count, created_at "
            "FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def failure_patterns(*, path: str | Path | None = None) -> list[dict[str, Any]]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT check_id, COUNT(DISTINCT run_id) AS run_count,
                   COUNT(*) AS failure_count, MAX(reason) AS example_reason,
                   MAX(fix_instruction) AS example_fix_instruction,
                   SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) AS resolved_count,
                   SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) AS unresolved_count
            FROM failed_checks
            GROUP BY check_id
            ORDER BY run_count DESC, failure_count DESC, check_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def failure_history(
    *,
    limit: int = 20,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT failed_checks.run_id, runs.topic, failed_checks.attempt,
                   failed_checks.check_id, failed_checks.reason,
                   failed_checks.evidence, failed_checks.fix_instruction,
                   failed_checks.resolved, failed_checks.resolved_by_attempt
            FROM failed_checks
            JOIN runs USING (run_id)
            ORDER BY runs.created_at DESC, failed_checks.attempt DESC,
                     failed_checks.check_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_feedback_notes(
    *,
    limit: int = 10,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT feedback_notes.run_id, runs.topic, feedback_notes.note,
                   feedback_notes.created_at
            FROM feedback_notes
            JOIN runs USING (run_id)
            ORDER BY feedback_notes.created_at DESC, feedback_notes.feedback_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_note(run_id: str, note: str, *, path: str | Path | None = None) -> None:
    if not note.strip():
        raise ValueError("note must not be empty.")
    with _connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if exists is None:
            raise ValueError(f"No recorded run exists with ID {run_id!r}.")
        connection.execute(
            "INSERT INTO feedback_notes (run_id, note) VALUES (?, ?)",
            (run_id, note.strip()),
        )


def get_generation_lessons(
    *,
    limit: int = 3,
    path: str | Path | None = None,
) -> list[dict[str, str]]:
    """Return short lessons from recurring failures and recent learner notes."""
    if limit < 1:
        raise ValueError("limit must be at least one.")
    with _connect(path) as connection:
        failures = connection.execute(
            """
            SELECT check_id, reason, fix_instruction,
                   COUNT(*) AS occurrences,
                   SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) AS resolutions
            FROM failed_checks
            WHERE fix_instruction != ''
            GROUP BY check_id, reason, fix_instruction
            ORDER BY occurrences DESC, resolutions DESC, check_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        notes = connection.execute(
            """
            SELECT note FROM feedback_notes
            ORDER BY created_at DESC, feedback_id DESC
            LIMIT ?
            """,
            (min(limit, 2),),
        ).fetchall()

    lessons = [
        {
            "kind": "failure",
            "text": (
                f"Check {row['check_id']} failed {row['occurrences']} time(s); "
                f"{row['resolutions'] or 0} immediate retry/retries passed. "
                f"Prior reason: {row['reason'][:180]} "
                f"Effective fix: {row['fix_instruction'][:240]}"
            ),
        }
        for row in failures
    ]
    lessons.extend(
        {"kind": "human_feedback", "text": f"Learner note: {row['note'][:200]}"}
        for row in notes
    )
    notes_first = [item for item in lessons if item["kind"] == "human_feedback"]
    failures_next = [item for item in lessons if item["kind"] == "failure"]
    return (notes_first + failures_next)[:limit]


def evolution_context(
    *,
    min_runs: int,
    replay_topics: int,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Summarize only recorded non-mock runs for candidate eligibility and replay."""
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT runs.run_id, runs.topic, runs.status, runs.attempt_count,
                   runs.report_json, runs.created_at,
                   failed_checks.check_id, failed_checks.reason,
                   failed_checks.fix_instruction
            FROM runs
            LEFT JOIN failed_checks USING (run_id)
            ORDER BY runs.created_at DESC, runs.rowid DESC, failed_checks.attempt DESC
            """
        ).fetchall()

    real_runs: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}
    for row in rows:
        report = json.loads(row["report_json"])
        models = report.get("model_names", {})
        generator_model = models.get("generation", "")
        if not generator_model or generator_model.casefold().startswith("mock"):
            continue
        run = real_runs.setdefault(
            row["run_id"],
            {
                "run_id": row["run_id"],
                "topic": row["topic"],
                "status": row["status"],
                "attempt_count": row["attempt_count"],
                "created_at": row["created_at"],
                "first_pass": bool(
                    report.get("attempts")
                    and report["attempts"][0].get("passed") is True
                ),
            },
        )
        if row["check_id"] is None:
            continue
        check = failures.setdefault(
            row["check_id"],
            {"check_id": row["check_id"], "run_ids": set(), "reasons": [], "fixes": []},
        )
        check["run_ids"].add(row["run_id"])
        if row["reason"] and row["reason"] not in check["reasons"]:
            check["reasons"].append(row["reason"])
        if row["fix_instruction"] and row["fix_instruction"] not in check["fixes"]:
            check["fixes"].append(row["fix_instruction"])

    chronic = [
        {
            "check_id": check["check_id"],
            "run_count": len(check["run_ids"]),
            "reasons": check["reasons"][:3],
            "fixes": check["fixes"][:3],
        }
        for check in failures.values()
        if len(check["run_ids"]) >= min_runs
    ]
    ordered_runs = list(real_runs.values())
    topics: list[str] = []
    for run in ordered_runs:
        if run["topic"] not in topics:
            topics.append(run["topic"])
        if len(topics) == replay_topics:
            break
    first_pass_count = sum(run["first_pass"] for run in ordered_runs)
    retry_count = sum(max(0, run["attempt_count"] - 1) for run in ordered_runs)
    total_runs = len(ordered_runs)
    return {
        "real_run_count": total_runs,
        "first_pass_count": first_pass_count,
        "first_pass_rate": first_pass_count / total_runs if total_runs else None,
        "retry_count": retry_count,
        "topics": topics,
        "chronic_failures": chronic,
    }
