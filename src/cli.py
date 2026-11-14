"""Command-line entry point for the bounded lesson-generation agent."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from src.agent import ROOT, run_lesson
from src.checks_code import CodeCheckError
from src.checks_llm import JudgeOutputError
from src.config import MAX_RETRIES, ConfigurationError, load_config
from src.llm import LLMError
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "run":
        return 2
    try:
        settings = load_config(require_live=not args.mock)
        if args.mock:
            settings = replace(settings, mock_llm=True)
        result = run_lesson(
            args.topic,
            settings=settings,
            max_retries=args.max_retries,
            inject_error=args.inject_error,
            output_dir=args.output_dir,
        )
    except (
        CodeCheckError,
        ConfigurationError,
        FactSourceError,
        JudgeOutputError,
        LLMError,
        OSError,
        RubricError,
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
    print(f"JSON report: {result.json_path}")
    print(f"Markdown report: {result.markdown_path}")
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
