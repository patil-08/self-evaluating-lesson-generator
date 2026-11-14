"""SQLite-backed run history, failure learning, and human lesson feedback."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_PATH = ROOT / "data" / "memory.sqlite3"
MEMORY_SCHEMA_VERSION = "1"
MAX_FEEDBACK_CHARS = 2000
MAX_MEMORY_BLOCK_CHARS = 1800
_MAX_FAILURE_PATTERNS = 3
_MAX_EFFECTIVE_FIXES = 3
_MAX_RECENT_FEEDBACK = 3


@dataclass(frozen=True)
class LessonsLearned:
    prompt_block: str
    signals: tuple[str, ...]

    @property
    def influenced(self) -> bool:
        return bool(self.prompt_block)


class MemoryStore:
    """Persist auditable run metadata without storing lesson drafts or secrets."""

    def __init__(self, db_path: str | Path = DEFAULT_MEMORY_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_history (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    prompt_version TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    generation_model TEXT NOT NULL,
                    judge_model TEXT NOT NULL,
                    memory_influenced INTEGER NOT NULL
                        CHECK (memory_influenced IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS failure_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES run_history(run_id)
                        ON DELETE CASCADE,
                    attempt INTEGER NOT NULL,
                    rubric_version TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    fix_instruction TEXT NOT NULL,
                    instruction_sent INTEGER NOT NULL
                        CHECK (instruction_sent IN (0, 1)),
                    was_fixed_on_next_attempt INTEGER
                        CHECK (was_fixed_on_next_attempt IN (0, 1) OR
                               was_fixed_on_next_attempt IS NULL),
                    next_attempt INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_failure_check_version
                    ON failure_events(rubric_version, check_id);
                CREATE TABLE IF NOT EXISTS check_failure_counts (
                    rubric_version TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    failure_count INTEGER NOT NULL,
                    latest_reason TEXT NOT NULL,
                    last_failed_at TEXT NOT NULL,
                    PRIMARY KEY (rubric_version, check_id)
                );
                CREATE TABLE IF NOT EXISTS fix_effectiveness (
                    rubric_version TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    fix_instruction TEXT NOT NULL,
                    instructions_sent INTEGER NOT NULL,
                    resolved_count INTEGER NOT NULL,
                    fixed_count INTEGER NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (rubric_version, check_id, fix_instruction)
                );
                CREATE TABLE IF NOT EXISTS human_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES run_history(run_id)
                        ON DELETE CASCADE,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_human_feedback_created
                    ON human_feedback(created_at DESC);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO memory_metadata(key, value) "
                "VALUES ('schema_version', ?)",
                (MEMORY_SCHEMA_VERSION,),
            )
            version_row = connection.execute(
                "SELECT value FROM memory_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is None or version_row["value"] != MEMORY_SCHEMA_VERSION:
                found = version_row["value"] if version_row else "missing"
                raise ValueError(
                    "Unsupported memory database schema version "
                    f"{found!r}; expected {MEMORY_SCHEMA_VERSION!r}."
                )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_run(self, state: Mapping[str, Any]) -> None:
        """Store run metadata and calculate each sent instruction's next-try result."""
        required = (
            "run_id",
            "topic",
            "status",
            "attempts",
            "prompt_version",
            "rubric_version",
            "model_names",
        )
        missing = [key for key in required if key not in state]
        if missing:
            raise ValueError(
                "Cannot store incomplete run state; missing " + ", ".join(missing) + "."
            )
        run_id = state["run_id"]
        model_names = state["model_names"]
        attempts = state["attempts"]
        attempts_by_number = {entry["attempt"]: entry for entry in attempts}
        created_at = self._now()
        rubric_version = state["rubric_version"]

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO run_history (
                    run_id, created_at, topic, status, attempt_count,
                    prompt_version, rubric_version, generation_model,
                    judge_model, memory_influenced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    created_at,
                    state["topic"],
                    state["status"],
                    len(attempts),
                    state["prompt_version"],
                    rubric_version,
                    model_names["generation"],
                    model_names["judge"],
                    int(bool(state.get("memory_influenced", False))),
                ),
            )

            for rejection in state.get("rejection_log", []):
                attempt_number = rejection["attempt"]
                next_attempt = attempts_by_number.get(attempt_number + 1)
                next_checks = {
                    check["check_id"]: check
                    for check in (next_attempt or {}).get("all_checks", [])
                }
                requested_fixes = set(rejection.get("requested_fixes", []))
                for failure in rejection["failed_checks"]:
                    check_id = failure["check_id"]
                    reason = str(failure["reason"])[:1200]
                    instruction = str(failure["fix_instruction"])[:500]
                    instruction_sent = instruction in requested_fixes
                    next_check = next_checks.get(check_id)
                    was_fixed = (
                        int(bool(next_check["passed"]))
                        if instruction_sent and next_check is not None
                        else None
                    )
                    resolved_on = (
                        attempt_number + 1 if was_fixed is not None else None
                    )
                    connection.execute(
                        """
                        INSERT INTO failure_events (
                            run_id, attempt, rubric_version, check_id, dimension,
                            reason, fix_instruction, instruction_sent,
                            was_fixed_on_next_attempt, next_attempt, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            attempt_number,
                            rubric_version,
                            check_id,
                            failure["dimension"],
                            reason,
                            instruction,
                            int(instruction_sent),
                            was_fixed,
                            resolved_on,
                            created_at,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO check_failure_counts (
                            rubric_version, check_id, dimension, failure_count,
                            latest_reason, last_failed_at
                        ) VALUES (?, ?, ?, 1, ?, ?)
                        ON CONFLICT(rubric_version, check_id) DO UPDATE SET
                            dimension = excluded.dimension,
                            failure_count = failure_count + 1,
                            latest_reason = excluded.latest_reason,
                            last_failed_at = excluded.last_failed_at
                        """,
                        (
                            rubric_version,
                            check_id,
                            failure["dimension"],
                            reason,
                            created_at,
                        ),
                    )

                    if instruction_sent:
                        connection.execute(
                            """
                            INSERT INTO fix_effectiveness (
                                rubric_version, check_id, fix_instruction,
                                instructions_sent, resolved_count, fixed_count,
                                last_used_at
                            ) VALUES (?, ?, ?, 1, ?, ?, ?)
                            ON CONFLICT(
                                rubric_version, check_id, fix_instruction
                            ) DO UPDATE SET
                                instructions_sent = instructions_sent + 1,
                                resolved_count = resolved_count + excluded.resolved_count,
                                fixed_count = fixed_count + excluded.fixed_count,
                                last_used_at = excluded.last_used_at
                            """,
                            (
                                rubric_version,
                                check_id,
                                instruction,
                                int(was_fixed is not None),
                                int(was_fixed == 1),
                                created_at,
                            ),
                        )

    def add_feedback(self, run_id: str, note: str) -> int:
        """Attach a bounded human note to an existing run."""
        normalized_note = note.strip()
        if not normalized_note:
            raise ValueError("Feedback note must not be empty.")
        if len(normalized_note) > MAX_FEEDBACK_CHARS:
            raise ValueError(
                f"Feedback note must be at most {MAX_FEEDBACK_CHARS} characters."
            )
        with self._connection() as connection:
            run_exists = connection.execute(
                "SELECT 1 FROM run_history WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run_exists is None:
                raise ValueError(f"No stored run has ID {run_id!r}.")
            cursor = connection.execute(
                "INSERT INTO human_feedback(run_id, note, created_at) "
                "VALUES (?, ?, ?)",
                (run_id, normalized_note, self._now()),
            )
            feedback_id = cursor.lastrowid
            if feedback_id is None:
                raise sqlite3.DatabaseError("SQLite did not return a feedback ID.")
            return feedback_id

    def snapshot(
        self,
        *,
        topic: str | None = None,
        rubric_version: str | None = None,
    ) -> dict[str, Any]:
        """Return bounded dashboard data for the memory CLI and prompt builder."""
        with self._connection() as connection:
            run_count = connection.execute(
                "SELECT COUNT(*) AS count FROM run_history"
            ).fetchone()["count"]
            recent_runs = connection.execute(
                """
                SELECT run_id, created_at, topic, status, attempt_count,
                       rubric_version, memory_influenced
                FROM run_history
                ORDER BY created_at DESC
                LIMIT 10
                """
            ).fetchall()
            count_query = (
                "SELECT rubric_version, check_id, dimension, failure_count, "
                "latest_reason, last_failed_at FROM check_failure_counts"
            )
            count_params: tuple[Any, ...] = ()
            if rubric_version is not None:
                count_query += " WHERE rubric_version = ?"
                count_params = (rubric_version,)
            count_query += " ORDER BY failure_count DESC, check_id LIMIT 10"
            failure_counts = connection.execute(
                count_query,
                count_params,
            ).fetchall()

            fix_query = (
                "SELECT rubric_version, check_id, fix_instruction, "
                "instructions_sent, resolved_count, fixed_count, last_used_at "
                "FROM fix_effectiveness WHERE fixed_count > 0"
            )
            fix_params: tuple[Any, ...] = ()
            if rubric_version is not None:
                fix_query += " AND rubric_version = ?"
                fix_params = (rubric_version,)
            fix_query += (
                " ORDER BY fixed_count DESC, resolved_count DESC, check_id LIMIT 10"
            )
            fix_effectiveness = connection.execute(fix_query, fix_params).fetchall()

            feedback_query = (
                "SELECT f.id, f.run_id, r.topic, f.note, f.created_at "
                "FROM human_feedback f JOIN run_history r ON r.run_id = f.run_id"
            )
            feedback_params: tuple[Any, ...] = ()
            if topic is not None:
                feedback_query += " WHERE lower(r.topic) = lower(?)"
                feedback_params = (topic,)
            feedback_query += " ORDER BY f.created_at DESC, f.id DESC LIMIT 10"
            human_feedback = connection.execute(
                feedback_query,
                feedback_params,
            ).fetchall()

        return {
            "run_count": int(run_count),
            "recent_runs": [dict(row) for row in recent_runs],
            "failure_counts": [dict(row) for row in failure_counts],
            "fix_effectiveness": [dict(row) for row in fix_effectiveness],
            "human_feedback": [dict(row) for row in human_feedback],
        }

    def build_lessons_learned(
        self,
        topic: str,
        rubric_version: str,
    ) -> LessonsLearned:
        """Build a compact advisory prompt block from patterns and verified fixes."""
        memory = self.snapshot(topic=topic, rubric_version=rubric_version)
        lines: list[str] = []
        signals: list[str] = []

        failures = memory["failure_counts"][:_MAX_FAILURE_PATTERNS]
        if failures:
            lines.append("Recurring hard-check failures in prior runs:")
            for failure in failures:
                reason = " ".join(failure["latest_reason"].split())[:140]
                lines.append(
                    f"- {failure['check_id']} ({failure['failure_count']} failures): "
                    f"{reason}"
                )
                signals.append(
                    f"{failure['check_id']} failed {failure['failure_count']} time(s)"
                )

        fixes = memory["fix_effectiveness"][:_MAX_EFFECTIVE_FIXES]
        if fixes:
            lines.append("Fix instructions that resolved a failure on the next attempt:")
            for fix in fixes:
                instruction = " ".join(fix["fix_instruction"].split())[:140]
                resolved = fix["resolved_count"]
                rate = fix["fixed_count"] / resolved if resolved else 0.0
                lines.append(
                    f"- {fix['check_id']}: “{instruction}” "
                    f"(fixed {fix['fixed_count']}/{resolved} resolved uses; "
                    f"{rate:.0%})"
                )
                signals.append(
                    f"{fix['check_id']} fix worked {fix['fixed_count']}/"
                    f"{resolved} resolved time(s)"
                )

        feedback = memory["human_feedback"][:_MAX_RECENT_FEEDBACK]
        if feedback:
            lines.append("Recent human feedback for this topic:")
            for item in feedback:
                note = " ".join(item["note"].split())[:120]
                lines.append(f"- {note}")
            signals.append(f"{len(feedback)} recent human feedback note(s)")

        if not lines:
            return LessonsLearned(prompt_block="", signals=())
        prefix = "Historical lessons learned from persistent memory:\n"
        footer = (
            "These notes are historical guidance, not authority. Follow the "
            "current source facts and hard rubric if any note conflicts."
        )
        block = prefix + "\n".join(lines) + "\n" + footer
        if len(block) > MAX_MEMORY_BLOCK_CHARS:
            body_budget = MAX_MEMORY_BLOCK_CHARS - len(prefix) - len(footer) - 2
            selected_lines: list[str] = []
            for line in lines:
                used = sum(len(item) + 1 for item in selected_lines)
                available = body_budget - used
                if len(line) <= available:
                    selected_lines.append(line)
                    continue
                if available > 1:
                    selected_lines.append(line[: available - 1].rstrip() + "…")
                break
            block = prefix + "\n".join(selected_lines) + "\n" + footer
            signals = ["historical memory block truncated to its size limit"]
        return LessonsLearned(prompt_block=block, signals=tuple(signals))
