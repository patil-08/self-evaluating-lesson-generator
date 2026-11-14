"""Run the versioned evaluator against known-good and deliberately flawed lessons."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.checks_code import CodeCheckError
from src.checks_llm import JudgeOutputError
from src.config import ConfigurationError, Settings, load_config
from src.evaluator import EvaluationResult, evaluate_lesson
from src.llm import LLMClient, LLMError
from src.rubric import RubricError, load_rubric
from src.sources import FactSourceError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures"
DEFAULT_REPORT_PATH = ROOT / "docs" / "calibration_report.md"
_HEADING_RE = re.compile(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Fixture:
    id: str
    lesson: str
    expected_pass: bool
    expected_fail_checks: frozenset[str]


@dataclass(frozen=True)
class FixtureResult:
    fixture: Fixture
    evaluation: EvaluationResult | None
    error: str | None


def _section_blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return text, []
    prefix = text[: matches[0].start()]
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = re.sub(r"[*_`]", "", match.group(2)).strip()
        blocks.append((heading, text[match.start() : end]))
    return prefix, blocks


def _mutate_lesson(lesson: str, mutation: dict[str, Any], fixture_id: str) -> str:
    mutation_type = mutation.get("type")
    if mutation_type == "append":
        extra = mutation.get("text")
        if not isinstance(extra, str) or not extra.strip():
            raise ValueError(f"{fixture_id}: append mutation needs non-empty text.")
        return lesson.rstrip() + "\n\n" + extra.strip() + "\n"

    if mutation_type == "remove_section":
        heading_to_remove = mutation.get("heading")
        prefix, blocks = _section_blocks(lesson)
        selected = [
            index
            for index, (heading, _) in enumerate(blocks)
            if heading.casefold() == str(heading_to_remove).casefold()
        ]
        if len(selected) != 1:
            raise ValueError(
                f"{fixture_id}: expected one section named {heading_to_remove!r}, "
                f"found {len(selected)}."
            )
        removed = selected[0]
        kept = [block for index, block in enumerate(blocks) if index != removed]
        return prefix + "".join(block for _, block in kept)

    if mutation_type == "swap_sections":
        first = mutation.get("first_heading")
        second = mutation.get("second_heading")
        prefix, blocks = _section_blocks(lesson)
        indices = {
            heading.casefold(): index
            for index, (heading, _) in enumerate(blocks)
        }
        try:
            first_index = indices[str(first).casefold()]
            second_index = indices[str(second).casefold()]
        except KeyError as error:
            raise ValueError(
                f"{fixture_id}: swap section heading was not found: {error.args[0]!r}."
            ) from error
        blocks[first_index], blocks[second_index] = blocks[second_index], blocks[first_index]
        return prefix + "".join(block for _, block in blocks)

    raise ValueError(f"{fixture_id}: unsupported fixture mutation {mutation_type!r}.")


def load_fixtures(manifest_path: Path = FIXTURE_DIR / "manifest.json") -> list[Fixture]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load calibration manifest {manifest_path}: {error}") from error
    entries = manifest.get("fixtures") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Calibration manifest must contain a 'fixtures' list.")

    loaded: dict[str, Fixture] = {}
    fixtures: list[Fixture] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each calibration fixture must be a JSON object.")
        fixture_id = entry.get("id")
        expected_pass = entry.get("expected_pass")
        expected_fail_checks = entry.get("expected_fail_checks")
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            raise ValueError("Each calibration fixture needs a non-empty ID.")
        if fixture_id in loaded:
            raise ValueError(f"Duplicate calibration fixture ID: {fixture_id}.")
        if not isinstance(expected_pass, bool):
            raise ValueError(f"{fixture_id}: expected_pass must be a boolean.")
        if (
            not isinstance(expected_fail_checks, list)
            or not all(isinstance(item, str) for item in expected_fail_checks)
        ):
            raise ValueError(f"{fixture_id}: expected_fail_checks must be a string list.")

        if "file" in entry:
            fixture_path = FIXTURE_DIR / entry["file"]
            try:
                lesson = fixture_path.read_text(encoding="utf-8")
            except OSError as error:
                raise ValueError(
                    f"{fixture_id}: could not read fixture {fixture_path}: {error}"
                ) from error
        else:
            base_id = entry.get("base_fixture")
            if base_id not in loaded:
                raise ValueError(f"{fixture_id}: base fixture {base_id!r} must come first.")
            lesson = loaded[base_id].lesson
            mutations = entry.get("mutations")
            if not isinstance(mutations, list) or not mutations:
                raise ValueError(f"{fixture_id}: flawed fixture needs mutations.")
            for mutation in mutations:
                if not isinstance(mutation, dict):
                    raise ValueError(f"{fixture_id}: each mutation must be an object.")
                lesson = _mutate_lesson(lesson, mutation, fixture_id)

        if expected_pass and expected_fail_checks:
            raise ValueError(f"{fixture_id}: a known-good fixture cannot expect failures.")
        if not expected_pass and not expected_fail_checks:
            raise ValueError(f"{fixture_id}: a flawed fixture must name expected failed checks.")
        fixture = Fixture(
            id=fixture_id,
            lesson=lesson,
            expected_pass=expected_pass,
            expected_fail_checks=frozenset(expected_fail_checks),
        )
        loaded[fixture_id] = fixture
        fixtures.append(fixture)

    good_count = sum(fixture.expected_pass for fixture in fixtures)
    flawed_count = len(fixtures) - good_count
    if good_count != 4 or flawed_count != 8:
        raise ValueError(
            f"Expected 4 good and 8 flawed fixtures; found {good_count} and {flawed_count}."
        )
    rubric_check_ids = {check.id for check in load_rubric().checks}
    for fixture in fixtures:
        unknown = fixture.expected_fail_checks - rubric_check_ids
        if unknown:
            raise ValueError(
                f"{fixture.id}: expected failure IDs are not in the rubric: "
                f"{', '.join(sorted(unknown))}."
            )
    return fixtures


def _run_mode(
    mode: str,
    settings: Settings,
    fixtures: list[Fixture],
) -> list[FixtureResult]:
    client = LLMClient(settings=settings)
    results: list[FixtureResult] = []
    for fixture in fixtures:
        try:
            evaluation = evaluate_lesson(fixture.lesson, client=client)
        except (
            CodeCheckError,
            ConfigurationError,
            FactSourceError,
            JudgeOutputError,
            LLMError,
            RubricError,
            ValueError,
            OSError,
        ) as error:
            message = str(error)
            if settings.api_key:
                message = message.replace(settings.api_key, "[REDACTED]")
            results.append(FixtureResult(fixture, None, f"{type(error).__name__}: {message}"))
        else:
            results.append(FixtureResult(fixture, evaluation, None))
    return results


def _status(result: FixtureResult, check_id: str) -> tuple[str, bool]:
    if result.error or result.evaluation is None:
        return "ERR", False
    actual = next(
        check.passed
        for check in result.evaluation.checks
        if check.check_id == check_id
    )
    expected = check_id not in result.fixture.expected_fail_checks
    return ("PASS" if actual else "FAIL"), actual == expected


def _mode_is_calibrated(results: list[FixtureResult]) -> bool:
    for result in results:
        if result.error or result.evaluation is None:
            return False
        fixture = result.fixture
        if fixture.expected_pass and not result.evaluation.passed:
            return False
        if not fixture.expected_pass:
            failed_ids = {
                check.check_id
                for check in result.evaluation.checks
                if not check.passed
            }
            if not fixture.expected_fail_checks.issubset(failed_ids):
                return False
    return True


def _format_mode_report(
    mode: str,
    results: list[FixtureResult],
    check_ids: list[str],
) -> tuple[str, bool]:
    good = [result for result in results if result.fixture.expected_pass]
    flawed = [result for result in results if not result.fixture.expected_pass]
    good_passed = sum(bool(result.evaluation and result.evaluation.passed) for result in good)
    expected_failure_count = sum(
        len(result.fixture.expected_fail_checks) for result in flawed
    )
    caught_count = 0
    for result in flawed:
        if result.evaluation:
            failed = {check.check_id for check in result.evaluation.checks if not check.passed}
            caught_count += len(result.fixture.expected_fail_checks & failed)
    exact_count = 0
    total_cells = len(results) * len(check_ids)
    for result in results:
        exact_count += sum(_status(result, check_id)[1] for check_id in check_ids)

    overall = _mode_is_calibrated(results)
    lines = [
        f"## {mode} run",
        "",
        f"- Known-good lessons passing: **{good_passed}/{len(good)}**.",
        f"- Expected flaw checks caught: **{caught_count}/{expected_failure_count}**.",
        f"- Exact per-check outcomes: **{exact_count}/{total_cells}**.",
        f"- Calibration result: **{'PASS' if overall else 'FAIL'}**.",
        "",
        "Each matrix cell shows `P` (pass) or `F` (fail). A check succeeds when "
        "that result matches the fixture's expectation; `!` marks a mismatch and "
        "`E` marks an evaluator error.",
        "",
        "| Fixture | Expected | Overall | " + " | ".join(check_ids) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in check_ids) + " |",
    ]
    for result in results:
        fixture = result.fixture
        if result.error:
            overall_cell = "ERROR"
            cells = ["E" for _ in check_ids]
        else:
            assert result.evaluation is not None
            overall_cell = "PASS" if result.evaluation.passed else "FAIL"
            cells = []
            for check_id in check_ids:
                actual, exact = _status(result, check_id)
                cells.append(f"{actual[0]}{'✓' if exact else '!'}")
        expected = "PASS" if fixture.expected_pass else (
            "FAIL: " + ", ".join(sorted(fixture.expected_fail_checks))
        )
        lines.append(
            f"| `{fixture.id}` | {expected} | {overall_cell} | "
            + " | ".join(cells)
            + " |"
        )

    mismatches = [
        (result, check_id)
        for result in results
        for check_id in check_ids
        if not _status(result, check_id)[1]
    ]
    if mismatches:
        lines.extend(["", "### Mismatches and errors", ""])
        for result, check_id in mismatches:
            if result.error:
                lines.append(f"- `{result.fixture.id}`: {result.error}")
                continue
            assert result.evaluation is not None
            check = next(
                check for check in result.evaluation.checks if check.check_id == check_id
            )
            expected = "PASS" if check_id not in result.fixture.expected_fail_checks else "FAIL"
            actual = "PASS" if check.passed else "FAIL"
            lines.append(
                f"- `{result.fixture.id}` / `{check_id}` expected {expected}, "
                f"got {actual}: {check.reason}"
            )
    else:
        lines.extend(
            [
                "",
                "No per-check mismatches were recorded in this run.",
            ]
        )
    return "\n".join(lines), overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock-only",
        action="store_true",
        help="Skip live-provider calibration even when credentials are configured.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Markdown report path (default: docs/calibration_report.md).",
    )
    args = parser.parse_args(argv)

    fixtures = load_fixtures()
    rubric = load_rubric()
    check_ids = [check.id for check in rubric.checks]
    settings_error: str | None = None
    try:
        settings = load_config(require_live=False)
    except ConfigurationError as error:
        settings_error = str(error)
        settings = Settings(
            mock_llm=True,
            api_key=None,
            base_url="https://api.openai.com/v1",
            gen_model="",
            judge_model="",
        )

    sections = [
        "# Evaluator Calibration Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Rubric version: `{rubric.version}`",
        f"- Fixture set: {len(fixtures)} lessons (4 known-good, 8 deliberately flawed).",
        "- Decision: every hard check is required; any missed expected failure or "
        "rejected good lesson is a calibration failure.",
        "",
    ]

    mock_results = _run_mode("mock", replace(settings, mock_llm=True), fixtures)
    mock_report, mock_passed = _format_mode_report("Mock", mock_results, check_ids)
    sections.append(mock_report)
    live_ready = bool(settings.api_key and settings.gen_model and settings.judge_model)
    live_passed: bool | None = None
    if live_ready and not args.mock_only:
        live_results = _run_mode("real", replace(settings, mock_llm=False), fixtures)
        live_report, live_passed = _format_mode_report("Real provider", live_results, check_ids)
        sections.extend(["", live_report])
    else:
        if args.mock_only:
            skip_reason = "Skipped by --mock-only."
        elif settings_error:
            skip_reason = f"Live configuration is invalid: {settings_error}"
        elif not settings.api_key:
            skip_reason = "Not run: no LLM_API_KEY is configured."
        else:
            skip_reason = "Not run: LLM_API_KEY is set, but GEN_MODEL and/or JUDGE_MODEL is missing."
        sections.extend(["", "## Real-provider run", "", f"- {skip_reason}"])

    sections.extend(
        [
            "",
            "## Calibration caveats",
            "",
            "Mock mode is deterministic and is intended for offline regression checks. "
            "Its judge uses explicit heuristics for the deliberate false-guarantee, "
            "unknown-jargon, missing-section/example, ordering, long-sentence, and "
            "idiom cases. For clean lessons, it verifies one representative grounded "
            "claim rather than performing full semantic claim extraction. Only a "
            "configured real judge can exercise the full prompt-based claim audit; "
            "its reported results remain model judgments, not proof of factual truth.",
            "",
            "The known-good lessons are curated against the local RAG facts. The "
            "deliberately flawed cases are generated from those lessons using the "
            "mutations recorded in `tests/fixtures/manifest.json`.",
            "",
        ]
    )
    report_text = "\n".join(sections)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_text, encoding="utf-8")
    print(f"Calibration report: {args.report}")
    print(f"Fixtures: {len(fixtures)} (4 good, 8 flawed)")
    print(f"Mock run: {'PASS' if mock_passed else 'FAIL'}")
    if live_passed is None:
        print("Real-provider run: not run (configuration incomplete or explicitly skipped)")
    else:
        print(f"Real-provider run: {'PASS' if live_passed else 'FAIL'}")
    return 0 if mock_passed and (live_passed is None or live_passed) else 1


if __name__ == "__main__":
    sys.exit(main())
