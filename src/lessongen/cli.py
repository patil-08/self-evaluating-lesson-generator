"""Command-line entry point for lesson runs, memory, feedback, and evolution."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from lessongen import memory
from lessongen.config import (
    CHRONIC_FAILURE_MIN_RUNS,
    MAX_RETRIES,
    MIN_REPLAY_TOPICS,
    load_config,
)
from lessongen.evolve import run as evolve
from lessongen.graph import INJECTION_TYPES, build, rejection_report
from lessongen.llm import LLMClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lessongen")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Generate, evaluate, and report a lesson.")
    run.add_argument("--topic", default="Introduction to RAG")
    run.add_argument(
        "--inject-error",
        nargs="?",
        const="false_claim",
        choices=INJECTION_TYPES,
        help="Inject one deliberate first-draft flaw for a retry demo.",
    )
    run.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    run.add_argument("--mock", action="store_true", help="Use deterministic offline models.")
    run.add_argument("--out", type=Path, help="Output directory for lesson and rejection logs.")

    history = commands.add_parser("memory", help="Show recent run history and repeated failures.")
    history.add_argument("--limit", type=int, default=20)

    feedback = commands.add_parser("feedback", help="Save a learner note for a run.")
    feedback.add_argument("--run", required=True, help="Run ID printed by the run command.")
    feedback.add_argument("--note", required=True)

    evolve_command = commands.add_parser(
        "evolve",
        help="Propose and gate a prompt update using real run history.",
    )
    evolve_command.add_argument("--min-runs", type=int, default=CHRONIC_FAILURE_MIN_RUNS)
    evolve_command.add_argument("--replay-topics", type=int, default=MIN_REPLAY_TOPICS)
    evolve_command.add_argument("--mock", action="store_true", help="Run the replay gate in mock mode.")
    evolve_command.add_argument("--report", type=Path, help="Append the report to this path.")
    evolve_command.add_argument("--decision-log", type=Path, help="Append decisions to this JSONL path.")
    return parser


def _slug(topic: str) -> str:
    return re.sub(r"\W+", "_", topic.lower()).strip("_")[:48] or "lesson"


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Lesson rejection log: {report['topic']}",
        "",
        f"- **Final status:** {report['final_status']}",
        f"- **Execution mode:** {report['execution_mode']}",
        f"- **Attempts:** {report['attempt_count']} (maximum retries: {report['max_retries']})",
        f"- **Rubric version:** {report['rubric_version']}",
        f"- **Generator prompt:** {report['prompt_versions']['generator']}",
        f"- **Judge prompt:** {report['prompt_versions']['judge']}",
        f"- **Generation model:** {report['model_names']['generation']}",
        f"- **Judge model:** {report['model_names']['judge']}",
        f"- **Tokens:** {report['usage']['total_tokens']} "
        f"(prompt {report['usage']['prompt_tokens']}, "
        f"completion {report['usage']['completion_tokens']})",
        f"- **Total model latency:** {report['usage']['latency_ms']:.2f} ms",
        "",
    ]
    for generation in report.get("generation_memory", []):
        memory_status = "influenced" if generation["influenced"] else "not used"
        lines.append(
            f"- **Attempt {generation['attempt']} memory:** {memory_status}"
        )
        for lesson in generation["lessons"]:
            lines.append(f"  - [{lesson['kind']}] {lesson['text']}")
    if report.get("generation_memory"):
        lines.append("")
    for attempt in report["attempts"]:
        lines.extend(
            [
                f"## Attempt {attempt['attempt']}: {'PASS' if attempt['passed'] else 'FAIL'}",
                "",
                f"**What changed:** {attempt['changes_from_previous']}",
                "",
            ]
        )
        if attempt["failed_checks"]:
            lines.append("**Failed checks**")
            for failure in attempt["failed_checks"]:
                lines.extend(
                    [
                        f"- `{failure['check_id']}` — {failure['reason']}",
                        f"  - Evidence: {failure['evidence'] or '(none)'}",
                        f"  - Fix instruction: {failure['fix_instruction']}",
                    ]
                )
            lines.append("")
        else:
            lines.extend(["All hard checks passed.", ""])
    return "\n".join(lines)


def _write_outputs(
    state: dict[str, Any],
    output_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = rejection_report(state)
    report["run_id"] = run_id
    (output_dir / "rejection_log.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "rejection_log.md").write_text(
        _markdown_report(report),
        encoding="utf-8",
    )
    if state["status"] == "SHIPPED":
        (output_dir / "best_draft.md").unlink(missing_ok=True)
        (output_dir / "lesson.md").write_text(state["lesson"], encoding="utf-8")
    else:
        (output_dir / "lesson.md").unlink(missing_ok=True)
        (output_dir / "best_draft.md").write_text(
            state["best_draft"],
            encoding="utf-8",
        )
    return report


def _run(args: argparse.Namespace) -> int:
    if args.max_retries < 0:
        raise ValueError("--max-retries must be zero or greater.")
    settings = load_config(require_live=not args.mock)
    if args.mock:
        settings = replace(settings, mock_llm=True)
    client = LLMClient(settings=settings)
    workflow = build(
        client=client,
        max_retries=args.max_retries,
        inject_error=args.inject_error,
    )
    state = workflow.invoke({"topic": args.topic})
    output_dir = args.out or Path("outputs") / _slug(args.topic)
    run_id = str(uuid.uuid4())
    report = _write_outputs(state, output_dir, run_id)
    memory.record_run(report)
    print(f"Execution mode: {report['execution_mode']}.")
    if state["status"] == "SHIPPED":
        print(f"Status: SHIPPED after {state['attempt_count']} attempt(s).")
        print(f"Lesson: {output_dir / 'lesson.md'}")
    else:
        print(f"Status: ESCALATED after {state['attempt_count']} attempt(s).")
        print(f"Best draft for human review: {output_dir / 'best_draft.md'}")
    print(f"Rejection logs: {output_dir / 'rejection_log.json'} and rejection_log.md")
    print(f"Run ID: {run_id}")
    return 0 if state["status"] == "SHIPPED" else 2


def _show_memory(limit: int) -> int:
    if limit < 1:
        raise ValueError("--limit must be at least one.")
    runs = memory.list_runs(limit=limit)
    patterns = memory.failure_patterns()
    failures = memory.failure_history(limit=limit)
    notes = memory.recent_feedback_notes()
    if not runs:
        print("No runs recorded yet.")
    else:
        for item in runs:
            print(
                f"{item['run_id']} | {item['status']} | "
                f"{item['attempt_count']} attempt(s) | {item['topic']}"
            )
    if patterns:
        print("\nRepeated failed checks:")
        for item in patterns:
            print(
                f"{item['check_id']}: {item['run_count']} run(s), "
                f"{item['failure_count']} rejection(s), "
                f"{item['resolved_count'] or 0} resolved by the next attempt"
            )
    if failures:
        print("\nFailure and fix history:")
        for item in failures:
            resolved = (
                f"resolved by attempt {item['resolved_by_attempt']}"
                if item["resolved"] == 1
                else "not resolved on the next attempt"
                if item["resolved"] == 0
                else "no retry outcome recorded"
            )
            print(
                f"{item['run_id']} attempt {item['attempt']} | {item['check_id']} | "
                f"{resolved}\n  Reason: {item['reason']}\n"
                f"  Fix: {item['fix_instruction'] or '(not recorded)'}"
            )
    if notes:
        print("\nRecent learner notes:")
        for note in notes:
            print(f"{note['run_id']} | {note['topic']}: {note['note']}")
    return 0


def _evolve(args: argparse.Namespace) -> int:
    if args.min_runs < 1:
        raise ValueError("--min-runs must be at least one.")
    if args.replay_topics < 1:
        raise ValueError("--replay-topics must be at least one.")
    settings = load_config(require_live=not args.mock)
    if args.mock:
        settings = replace(settings, mock_llm=True)
    decision = evolve(
        settings=settings,
        min_runs=args.min_runs,
        replay_topics=args.replay_topics,
        report_path=args.report,
        decision_log_path=args.decision_log,
    )
    print(f"Evolution: {decision['decision']} ({decision['replay_mode']} replay).")
    print(f"Reason: {decision['reason']}")
    if decision["candidate_prompt"]:
        print(f"Candidate: {decision['candidate_prompt']}")
    if decision["adopted_prompt"]:
        print(f"Adopted prompt: {decision['adopted_prompt']}")
    print(f"Report: {args.report or 'docs/evolution_report.md'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "memory":
            return _show_memory(args.limit)
        if args.command == "feedback":
            memory.add_note(args.run, args.note)
            print(f"Feedback note saved for run {args.run}.")
            return 0
        if args.command == "evolve":
            return _evolve(args)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"lessongen: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
