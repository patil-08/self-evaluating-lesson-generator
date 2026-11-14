from __future__ import annotations

import json

from src.agent import run_lesson
from src.cli import main
from src.config import Settings
from src.llm import LLMClient, ModelRole
from src.memory import MAX_MEMORY_BLOCK_CHARS, MemoryStore

_FIX = "Define each technical term in plain words at its first use."


def _recorded_run(run_id: str = "prior-run") -> dict:
    failed_check = {
        "check_id": "JARG-01",
        "dimension": "no_unexplained_jargon",
        "reason": "The first use of embedding was not defined nearby.",
        "fix_instruction": _FIX,
    }
    return {
        "run_id": run_id,
        "topic": "Introduction to RAG",
        "status": "passed",
        "attempts": [
            {
                "attempt": 1,
                "all_checks": [{"check_id": "JARG-01", "passed": False}],
            },
            {
                "attempt": 2,
                "all_checks": [{"check_id": "JARG-01", "passed": True}],
            },
        ],
        "rejection_log": [
            {
                "attempt": 1,
                "failed_checks": [failed_check],
                "requested_fixes": [_FIX],
            }
        ],
        "prompt_version": "1.0",
        "rubric_version": "1.0",
        "model_names": {
            "generation": "mock-generation",
            "judge": "mock-judge",
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


def test_memory_persists_failures_and_measures_next_attempt_fix(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    first_store = MemoryStore(db_path)
    first_store.record_run(_recorded_run())

    reopened_store = MemoryStore(db_path)
    snapshot = reopened_store.snapshot(rubric_version="1.0")
    failure = snapshot["failure_counts"][0]
    effectiveness = snapshot["fix_effectiveness"][0]
    learned = reopened_store.build_lessons_learned(
        "Introduction to RAG",
        "1.0",
    )

    assert snapshot["run_count"] == 1
    assert (failure["check_id"], failure["failure_count"]) == ("JARG-01", 1)
    assert failure["latest_reason"] == (
        "The first use of embedding was not defined nearby."
    )
    assert effectiveness["instructions_sent"] == 1
    assert effectiveness["resolved_count"] == 1
    assert effectiveness["fixed_count"] == 1
    assert "fixed 1/1" in learned.prompt_block
    assert "JARG-01 failed 1 time(s)" in learned.signals
    assert len(learned.prompt_block) <= MAX_MEMORY_BLOCK_CHARS
    assert learned.prompt_block.endswith(
        "current source facts and hard rubric if any note conflicts."
    )


def test_feedback_and_memory_cli_store_and_display_human_notes(
    tmp_path,
    capsys,
) -> None:
    db_path = tmp_path / "memory.sqlite3"
    MemoryStore(db_path).record_run(_recorded_run())

    feedback_exit = main(
        [
            "feedback",
            "--run",
            "prior-run",
            "--note",
            "Keep the school notice example; define new terms immediately.",
            "--memory-db",
            str(db_path),
        ]
    )
    assert feedback_exit == 0
    assert "Saved feedback" in capsys.readouterr().out

    memory_exit = main(["memory", "--memory-db", str(db_path)])
    output = capsys.readouterr().out
    assert memory_exit == 0
    assert "Stored runs: 1" in output
    assert "JARG-01 (1.0): 1" in output
    assert "1/1 resolved" in output
    assert "Keep the school notice example" in output


def test_memory_block_stays_bounded_and_keeps_rubric_precedence(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    for index in range(3):
        run = _recorded_run(f"prior-run-{index}")
        check_id = f"JARG-{index + 1:02d}"
        instruction = f"f{index}" * 250
        failure = run["rejection_log"][0]["failed_checks"][0]
        failure["check_id"] = check_id
        failure["reason"] = "reason " * 150
        failure["fix_instruction"] = instruction
        run["rejection_log"][0]["requested_fixes"] = [instruction]
        run["attempts"][0]["all_checks"][0]["check_id"] = check_id
        run["attempts"][1]["all_checks"][0]["check_id"] = check_id
        store.record_run(run)
        store.add_feedback(run["run_id"], "note " * 400)

    learned = store.build_lessons_learned("Introduction to RAG", "1.0")

    assert len(learned.prompt_block) <= MAX_MEMORY_BLOCK_CHARS
    assert learned.prompt_block.endswith(
        "current source facts and hard rubric if any note conflicts."
    )
    assert "Recurring hard-check failures" in learned.prompt_block
    assert "Recent human feedback" in learned.prompt_block
    assert any("fix worked" in signal for signal in learned.signals)


def test_prompt_receives_memory_and_report_logs_its_influence(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    memory = MemoryStore(db_path)
    memory.record_run(_recorded_run())
    memory.add_feedback(
        "prior-run",
        "Keep the school notice example and explain terms on first use.",
    )

    class RecordingClient(LLMClient):
        generation_prompts: list[str] = []

        def complete(self, prompt, *, role=ModelRole.GENERATION, **kwargs):
            if role is ModelRole.GENERATION:
                self.generation_prompts.append(prompt)
            return super().complete(prompt, role=role, **kwargs)

    client = RecordingClient(settings=_mock_settings())
    result = run_lesson(
        "Introduction to RAG",
        client=client,
        output_dir=tmp_path / "outputs",
        memory_store=memory,
    )

    report = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert result.state["status"] == "passed"
    assert "Historical lessons learned from persistent memory" in (
        client.generation_prompts[0]
    )
    assert "Keep the school notice example" in client.generation_prompts[0]
    assert report["memory_influenced"] is True
    assert "1 recent human feedback note(s)" in report["memory_signals"]
    assert "**Memory influenced generation:** yes" in (
        result.markdown_path.read_text(encoding="utf-8")
    )
