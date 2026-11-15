"""Calibrate hard-check behavior against labeled lesson fixtures."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from lessongen.config import Settings
from lessongen.evaluator import EvaluationResult, evaluate_lesson, load_rubric
from lessongen.llm import LLMClient

FIXTURE_DIR = ROOT / "tests" / "fixtures"
MANIFEST_PATH = FIXTURE_DIR / "manifest_lessongen.json"
DEFAULT_REPORT_PATH = ROOT / "docs" / "calibration_report.md"


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    kind: str
    lesson: str
    expected_failures: frozenset[str]


@dataclass(frozen=True)
class FixtureResult:
    fixture: Fixture
    evaluation: EvaluationResult

    @property
    def failed_checks(self) -> frozenset[str]:
        return frozenset(
            check.check_id for check in self.evaluation.checks if not check.passed
        )


def load_fixtures(manifest_path: str | Path = MANIFEST_PATH) -> list[Fixture]:
    path = Path(manifest_path)
    try:
        manifest: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load calibration manifest {path}: {error}") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("fixtures"), list):
        raise ValueError("Calibration manifest must contain a fixtures list.")

    fixture_dir = path.parent
    fixtures = []
    seen: set[str] = set()
    known_check_ids = {check["id"] for check in load_rubric()["checks"]}
    for item in manifest["fixtures"]:
        if not isinstance(item, dict):
            raise ValueError("Each calibration fixture must be an object.")
        fixture_id = item.get("id")
        kind = item.get("kind")
        expected = item.get("expected_failures")
        if (
            not isinstance(fixture_id, str)
            or fixture_id in seen
            or not isinstance(kind, str)
            or kind not in {"good", "flawed"}
            or not isinstance(expected, list)
            or not all(isinstance(check_id, str) for check_id in expected)
        ):
            raise ValueError(f"Invalid calibration fixture metadata: {item!r}.")
        unknown_checks = set(expected) - known_check_ids
        if unknown_checks:
            raise ValueError(
                f"Fixture {fixture_id!r} references unknown checks: "
                f"{sorted(unknown_checks)}."
            )
        if (kind == "good" and expected) or (kind == "flawed" and not expected):
            raise ValueError(
                f"Fixture {fixture_id!r} has expectations inconsistent with {kind!r}."
            )
        seen.add(fixture_id)
        relative_path = item.get("path")
        if not isinstance(relative_path, str):
            raise ValueError(f"Fixture {fixture_id!r} needs a lesson path.")
        lesson_path = (fixture_dir / relative_path).resolve()
        if fixture_dir.resolve() not in lesson_path.parents:
            raise ValueError(f"Fixture {fixture_id!r} path escapes the fixture folder.")
        try:
            lesson = lesson_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"Cannot read fixture {fixture_id!r}: {error}") from error
        fixtures.append(Fixture(fixture_id, kind, lesson, frozenset(expected)))
    return fixtures


def _make_mock_client() -> LLMClient:
    return LLMClient(
        settings=Settings(
            mock_llm=True,
            api_key=None,
            base_url="https://api.openai.com/v1",
            gen_model="",
            judge_model="",
        )
    )


def _ratio(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.1%}" if denominator else "n/a"


def _metrics(results: list[FixtureResult]) -> dict[str, int]:
    good = [item for item in results if item.fixture.kind == "good"]
    flawed = [item for item in results if item.fixture.kind == "flawed"]
    tp = sum(not item.evaluation.passed for item in flawed)
    fn = len(flawed) - tp
    fp = sum(not item.evaluation.passed for item in good)
    tn = len(good) - fp
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _check_metrics(
    results: list[FixtureResult],
    check_ids: list[str],
) -> list[tuple[str, int, int, int, str, str]]:
    metrics = []
    for check_id in check_ids:
        tp = sum(
            check_id in item.fixture.expected_failures and check_id in item.failed_checks
            for item in results
        )
        fp = sum(
            check_id not in item.fixture.expected_failures and check_id in item.failed_checks
            for item in results
        )
        fn = sum(
            check_id in item.fixture.expected_failures and check_id not in item.failed_checks
            for item in results
        )
        metrics.append((check_id, tp, fp, fn, _ratio(tp, tp + fp), _ratio(tp, tp + fn)))
    return metrics


def render_report(results: list[FixtureResult], mode: str = "mock") -> str:
    rubric = load_rubric()
    check_ids = [check["id"] for check in rubric["checks"]]
    metrics = _metrics(results)
    total_flawed = sum(item.fixture.kind == "flawed" for item in results)
    caught_flaws = sum(
        item.fixture.kind == "flawed"
        and item.fixture.expected_failures.issubset(item.failed_checks)
        for item in results
    )
    good = [item for item in results if item.fixture.kind == "good"]
    good_passed = sum(item.evaluation.passed for item in good)
    lines = [
        "# Calibration Report",
        "",
        f"- **Run mode:** {mode}",
        f"- **Rubric version:** {rubric['version']}",
        f"- **Fixtures:** {len(results)} ({len(good)} good, {total_flawed} flawed)",
        f"- **Targeted flaw checks caught:** {caught_flaws}/{total_flawed}",
        f"- **Good lessons passed:** {good_passed}/{len(good)}",
        "",
        "## Overall lesson-level metrics",
        "",
        "A lesson is predicted flawed when any hard check rejects it. A planted flaw",
        "is a positive case; a known-good lesson is a negative case.",
        "",
        "| Metric | Count | Rate |",
        "| --- | ---: | ---: |",
        f"| True positives | {metrics['tp']} | {_ratio(metrics['tp'], metrics['tp'] + metrics['fn'])} recall |",
        f"| False positives | {metrics['fp']} | {_ratio(metrics['fp'], metrics['fp'] + metrics['tn'])} of good lessons rejected |",
        f"| False negatives | {metrics['fn']} | {_ratio(metrics['fn'], metrics['fn'] + metrics['tp'])} of flawed lessons shipped |",
        f"| True negatives | {metrics['tn']} | {_ratio(metrics['tn'], metrics['tn'] + metrics['fp'])} specificity |",
        f"| Precision | - | {_ratio(metrics['tp'], metrics['tp'] + metrics['fp'])} |",
        f"| Recall | - | {_ratio(metrics['tp'], metrics['tp'] + metrics['fn'])} |",
        "",
        "## Fixture-by-fixture results",
        "",
        "| Fixture | Planted flaw | Expected failed checks | Actual failed checks | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in results:
        expected = ", ".join(sorted(item.fixture.expected_failures)) or "none"
        actual = ", ".join(sorted(item.failed_checks)) or "none"
        matches = item.failed_checks == item.fixture.expected_failures
        result = "PASS" if matches else "MISMATCH"
        label = (
            "known-good lesson"
            if item.fixture.kind == "good"
            else "deliberately flawed lesson"
        )
        lines.append(f"| {item.fixture.fixture_id} | {label} | {expected} | {actual} | {result} |")
    lines.extend(
        [
            "",
            "## Per-check precision and recall",
            "",
            "| Check | TP | FP | FN | Precision | Recall |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for check_id, tp, fp, fn, precision, recall in _check_metrics(results, check_ids):
        lines.append(f"| {check_id} | {tp} | {fp} | {fn} | {precision} | {recall} |")
    lines.extend(
        [
            "",
            "`n/a` means no fixture planted that check as a positive, so its "
            "check-specific recall is not measured.",
        ]
    )
    mismatch_count = sum(
        item.failed_checks != item.fixture.expected_failures for item in results
    )
    lines.extend(
        [
            "",
            "## Interpretation and limitations",
            "",
            f"- Exact expected-check mismatches: **{mismatch_count}**.",
            "- This report uses deterministic mock-judge rules; it measures regression behavior, not real-model judgment quality.",
            "- The semantic mock recognizes only the deliberately planted patterns. Passing this suite does not establish that a live judge is trustworthy on unseen lessons.",
            "- The four good lessons are hand-authored variations of one topic and source pack, so this is a narrow calibration set.",
            "- The wrong-order fixture also fails JARG-01 because moving the process section first exposes technical terms before their definitions.",
            "- A live calibration run and human review are still required before making reliability claims.",
            "",
        ]
    )
    return "\n".join(lines)


def run_calibration(
    *,
    output_path: str | Path = DEFAULT_REPORT_PATH,
) -> tuple[list[FixtureResult], str]:
    fixtures = load_fixtures()
    client = _make_mock_client()
    results = [
        FixtureResult(fixture, evaluate_lesson(fixture.lesson, client=client))
        for fixture in fixtures
    ]
    report = render_report(results, mode="mock (deterministic)")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")
    return results, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Markdown report path (default: docs/calibration_report.md)",
    )
    args = parser.parse_args()
    results, report = run_calibration(output_path=args.output)
    print(report)
    return int(any(item.failed_checks != item.fixture.expected_failures for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
