"""Command-line entry point for the bounded lesson-generation agent."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

from src.agent import ROOT, run_lesson
from src.checks_code import CodeCheckError
from src.checks_llm import JudgeOutputError
from src.config import MAX_RETRIES, ConfigurationError, load_config
from src.evolution import DEFAULT_CHANGELOG, DEFAULT_EVOLUTION_REPORT, run_evolution
from src.llm import LLMError
from src.memory import DEFAULT_MEMORY_PATH, MemoryStore
from src.rubric import RubricError
from src.sources import FactSourceError


def _max_retries(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer from 0 to 2") from error
    if not 0 <= parsed <= MAX_RETRIES:
        raise argparse.ArgumentTypeError(
            f"must be between 0 and {MAX_RETRIES} (the assignment limit)"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Generate, evaluate, and log a beginner lesson.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run the lesson-generation graph")
    run_parser.add_argument("--topic", required=True, help="lesson topic")
    run_parser.add_argument(
        "--inject-error",
        choices=("false_claim", "jargon", "no_example", "bad_order", "long_sentences"),
        help="add one deliberate first-draft flaw to demonstrate rejection and repair",
    )
    run_parser.add_argument(
        "--max-retries",
        type=_max_retries,
        default=MAX_RETRIES,
        help=f"regeneration attempts after the first draft (0-{MAX_RETRIES})",
    )
    run_parser.add_argument(
        "--mock",
        action="store_true",
        help="use deterministic offline generation and judging",
    )
    run_parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs",
        help="directory for the JSON and Markdown run reports",
    )
    run_parser.add_argument(
        "--memory-db",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="SQLite memory database path",
    )
    feedback_parser = subparsers.add_parser(
        "feedback",
        help="attach human feedback to a stored run",
    )
    feedback_parser.add_argument("--run", required=True, help="stored run ID")
    feedback_parser.add_argument("--note", required=True, help="feedback text")
    feedback_parser.add_argument(
        "--memory-db",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="SQLite memory database path",
    )
    memory_parser = subparsers.add_parser(
        "memory",
        help="show persistent run and learning memory",
    )
    memory_parser.add_argument(
        "--memory-db",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="SQLite memory database path",
    )
    evolve_parser = subparsers.add_parser(
        "evolve",
        help="propose a generator prompt from real failure evidence",
    )
    evolve_parser.add_argument(
        "--memory-db",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="SQLite memory database path",
    )
    evolve_parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_EVOLUTION_REPORT,
        help="evolution report path",
    )
    evolve_parser.add_argument(
        "--changelog",
        type=Path,
        default=DEFAULT_CHANGELOG,
        help="append-only prompt evolution changelog",
    )
    return parser


def _show_memory(memory: MemoryStore) -> None:
    snapshot = memory.snapshot()
    print(f"Memory database: {memory.db_path}")
    print(f"Stored runs: {snapshot['run_count']}")
    print("Recent runs:")
    if not snapshot["recent_runs"]:
        print("- None")
    for run in snapshot["recent_runs"]:
        influence = "yes" if run["memory_influenced"] else "no"
        print(
            f"- {run['run_id']} | {run['topic']} | {run['status']} | "
            f"{run['attempt_count']} attempt(s) | memory influenced: {influence}"
        )

    print("Per-check failure counts:")
    if not snapshot["failure_counts"]:
        print("- None")
    for failure in snapshot["failure_counts"]:
        print(
            f"- {failure['check_id']} ({failure['rubric_version']}): "
            f"{failure['failure_count']} - {failure['latest_reason']}"
        )

    print("Fix effectiveness (fixed / resolved next attempts):")
    if not snapshot["fix_effectiveness"]:
        print("- No fixes have resolved a failure yet.")
    for fix in snapshot["fix_effectiveness"]:
        print(
            f"- {fix['check_id']}: {fix['fixed_count']}/{fix['resolved_count']} "
            f"resolved - {fix['fix_instruction']}"
        )

    print("Human feedback:")
    if not snapshot["human_feedback"]:
        print("- None")
    for item in snapshot["human_feedback"]:
        print(f"- {item['run_id']} | {item['topic']}: {item['note']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        memory = MemoryStore(args.memory_db)
        if args.command == "memory":
            _show_memory(memory)
            return 0
        if args.command == "feedback":
            feedback_id = memory.add_feedback(args.run, args.note)
            print(f"Saved feedback #{feedback_id} for run {args.run}.")
            return 0
        if args.command == "evolve":
            settings = load_config(require_live=False)
            result = run_evolution(
                memory,
                settings,
                report_path=args.report,
                changelog_path=args.changelog,
            )
            print(f"Evolution report: {result.report_path}")
            print(f"Decision: {result.decision}")
            if result.candidate_path:
                print(f"Candidate prompt: {result.candidate_path}")
            return 0

        settings = load_config(require_live=not args.mock)
        if args.mock:
            settings = replace(settings, mock_llm=True)
        result = run_lesson(
            args.topic,
            settings=settings,
            max_retries=args.max_retries,
            inject_error=args.inject_error,
            output_dir=args.output_dir,
            memory_store=memory,
        )
    except (
        CodeCheckError,
        ConfigurationError,
        FactSourceError,
        JudgeOutputError,
        LLMError,
        OSError,
        RubricError,
        sqlite3.Error,
        ValueError,
    ) as error:
        message = str(error)
        active_key = None
        try:
            active_key = load_config(require_live=False).api_key
        except ConfigurationError:
            pass
        if active_key:
            message = message.replace(active_key, "[REDACTED]")
        print(f"Run failed: {type(error).__name__}: {message}", file=sys.stderr)
        return 1

    state = result.state
    print(f"Run status: {state['status']}")
    print(f"Run ID: {state['run_id']}")
    print(f"JSON report: {result.json_path}")
    print(f"Markdown report: {result.markdown_path}")
    print(
        "Memory influenced generation: "
        + ("yes" if state["memory_influenced"] else "no")
    )
    if state["memory_signals"]:
        print("Memory signals: " + "; ".join(state["memory_signals"]))
    print()
    if state["final_lesson"] is not None:
        print("Passing lesson:")
        print(state["final_lesson"])
    else:
        print("No lesson passed. The best draft is retained as unapproved in the report.")
    print()
    print("Rejection log:")
    if not state["rejection_log"]:
        print("No rejected drafts.")
    else:
        for rejection in state["rejection_log"]:
            print(f"Attempt {rejection['attempt']}:")
            for failed in rejection["failed_checks"]:
                evidence = failed["evidence_quote"] or "(omission)"
                print(
                    f"- {failed['check_id']}: {failed['reason']} "
                    f"Evidence: {evidence!r} "
                    f"Fix: {failed['fix_instruction']}"
                )
            if rejection.get("changes_on_retry"):
                print(f"  Retry changes: {rejection['changes_on_retry']}")
    return 0 if state["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
