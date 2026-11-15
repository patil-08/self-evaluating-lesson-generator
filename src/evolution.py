"""Evidence-gated prompt evolution with explicit calibration and replay checks."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent import run_lesson
from src.checks_code import CodeCheckError
from src.checks_llm import JudgeOutputError
from src.config import MAX_RETRIES, ConfigurationError, Settings
from src.llm import LLMClient, LLMError
from src.memory import MemoryStore
from src.prompt_registry import (
    PROMPTS_DIR,
    PromptSpec,
    activate_prompt,
    get_active_prompt,
)
from src.rubric import RubricError, load_rubric
from src.sources import FactSourceError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVOLUTION_REPORT = ROOT / "docs" / "evolution_report.md"
DEFAULT_CHANGELOG = ROOT / "CHANGELOG.md"

# Require three different real runs so a deliberate injection or one poor sample
# cannot create a "chronic" failure and rewrite a production prompt.
CHRONIC_FAILURE_MIN_RUNS = 3
# The small replay needs several source-compatible topics, not repeated runs of one topic.
MIN_REPLAY_TOPICS = 3

_REPEAT_FAILURE_GUIDANCE = {
    "ACC-01": (
        "Before returning, audit each factual sentence against the supplied "
        "source facts and remove claims they do not support."
    ),
    "BEGIN-01": (
        "After drafting, reread the lesson as a learner with no technical "
        "background and replace assumed knowledge with direct explanations."
    ),
    "BEGIN-02": (
        "Run a sentence-length pass and split any sentence over the rubric limit."
    ),
    "JARG-01": (
        "Scan technical terms in order and define each term plainly at its "
        "first use, not only in the glossary."
    ),
    "JARG-02": (
        "Remove specialized words unless they are needed; define each needed "
        "term near its first use."
    ),
    "EXAMPLE-01": (
        "Include a familiar everyday situation and explicitly connect its "
        "actions to the lesson's concept."
    ),
}


@dataclass(frozen=True)
class ReplayMetrics:
    prompt_version: str
    run_count: int
    first_pass_count: int
    retry_count: int

    @property
    def first_pass_rate(self) -> float:
        return (
            self.first_pass_count / self.run_count
            if self.run_count
            else 0.0
        )


@dataclass(frozen=True)
class EvolutionResult:
    report_path: Path
    decision: str
    adopted: bool
    candidate_path: Path | None


def _next_candidate_spec(active: PromptSpec) -> PromptSpec:
    next_major = int(active.version.split(".", 1)[0]) + 1
    while True:
        filename = f"generator_v{next_major}.txt"
        path = PROMPTS_DIR / filename
        if not path.exists():
            return PromptSpec(version=f"{next_major}.0", path=path)
        next_major += 1


def _make_candidate_text(
    active: PromptSpec,
    chronic_failures: list[dict[str, Any]],
    effective_fixes: list[dict[str, Any]],
) -> str:
    base = active.path.read_text(encoding="utf-8").rstrip()
    fixes_by_check: dict[str, list[dict[str, Any]]] = {}
    for fix in effective_fixes:
        fixes_by_check.setdefault(fix["check_id"], []).append(fix)

    additions = [
        "",
        "## Additional safeguards from repeated run evidence",
        "",
        "Use these extra checks before returning the lesson. They do not replace "
        "the versioned hard rubric or source facts.",
    ]
    for failure in chronic_failures:
        check_id = failure["check_id"]
        successful = fixes_by_check.get(check_id, [])
        if successful:
            learned = successful[0]["fix_instruction"]
            emphasis = (
                f"Prior retries resolved this failure with: {learned}"
            )
        else:
            emphasis = _REPEAT_FAILURE_GUIDANCE.get(
                check_id,
                "Check the lesson specifically against this hard requirement.",
            )
        additions.append(f"- For {check_id}: {emphasis}")
    return base + "\n" + "\n".join(additions) + "\n"


def _create_candidate(
    active: PromptSpec,
    chronic_failures: list[dict[str, Any]],
    effective_fixes: list[dict[str, Any]],
) -> PromptSpec:
    candidate = _next_candidate_spec(active)
    text = _make_candidate_text(active, chronic_failures, effective_fixes)
    with candidate.path.open("x", encoding="utf-8", newline="\n") as prompt_file:
        prompt_file.write(text)
    return candidate


def _calibration_summary() -> dict[str, Any]:
    from scripts.calibrate import _mode_is_calibrated, _run_mode, load_fixtures

    fixtures = load_fixtures()
    settings = Settings(
        mock_llm=True,
        api_key=None,
        base_url="https://api.openai.com/v1",
        gen_model="",
        judge_model="",
    )
    results = _run_mode("mock", settings, fixtures)
    good = [item for item in results if item.fixture.expected_pass]
    flawed = [item for item in results if not item.fixture.expected_pass]
    good_passed = sum(
        bool(item.evaluation and item.evaluation.passed) for item in good
    )
    expected_flaws = sum(len(item.fixture.expected_fail_checks) for item in flawed)
    caught_flaws = 0
    exact_checks = 0
    total_checks = 0
    for item in results:
        if item.evaluation is None:
            continue
        failed_ids = {
            check.check_id
            for check in item.evaluation.checks
            if not check.passed
        }
        caught_flaws += len(item.fixture.expected_fail_checks & failed_ids)
        total_checks += len(item.evaluation.checks)
        if item.fixture.expected_pass:
            exact_checks += sum(check.passed for check in item.evaluation.checks)
        else:
            exact_checks += sum(
                (check.check_id in item.fixture.expected_fail_checks)
                == (not check.passed)
                for check in item.evaluation.checks
            )
    return {
        "passed": _mode_is_calibrated(results),
        "good_passed": good_passed,
        "good_total": len(good),
        "expected_flaws": expected_flaws,
        "caught_flaws": caught_flaws,
        "exact_checks": exact_checks,
        "total_checks": total_checks,
        "fixtures": len(fixtures),
    }


def _eligible_replay_topics(history: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for row in history["real_topics"]:
        topic = row["topic"].strip()
        normalized = topic.casefold()
        if "rag" not in normalized or normalized in seen:
            continue
        seen.add(normalized)
        topics.append(topic)
    return topics[:MIN_REPLAY_TOPICS]


def _run_prompt_replay(
    active: PromptSpec,
    candidate: PromptSpec,
    topics: list[str],
    settings: Settings,
) -> tuple[ReplayMetrics, ReplayMetrics]:
    client = LLMClient(settings=settings)
    totals: dict[str, dict[str, int]] = {
        "baseline": {"first_pass": 0, "retries": 0},
        "candidate": {"first_pass": 0, "retries": 0},
    }
    with tempfile.TemporaryDirectory(prefix="lesson-prompt-replay-") as tmp:
        replay_root = Path(tmp)
        for label, prompt in (("baseline", active), ("candidate", candidate)):
            for index, topic in enumerate(topics, start=1):
                run_dir = replay_root / f"{label}_{index}"
                result = run_lesson(
                    topic,
                    client=client,
                    max_retries=MAX_RETRIES,
                    output_dir=run_dir / "outputs",
                    memory_store=MemoryStore(run_dir / "memory.sqlite3"),
                    prompt_version=prompt.version,
                    prompt_path=prompt.path,
                )
                attempts = result.state["attempts"]
                if attempts and attempts[0]["status"] == "passed":
                    totals[label]["first_pass"] += 1
                totals[label]["retries"] += max(0, len(attempts) - 1)

    return (
        ReplayMetrics(
            prompt_version=active.version,
            run_count=len(topics),
            first_pass_count=totals["baseline"]["first_pass"],
            retry_count=totals["baseline"]["retries"],
        ),
        ReplayMetrics(
            prompt_version=candidate.version,
            run_count=len(topics),
            first_pass_count=totals["candidate"]["first_pass"],
            retry_count=totals["candidate"]["retries"],
        ),
    )


def _adoption_allowed(
    *,
    calibration_not_worse: bool,
    baseline: ReplayMetrics,
    candidate: ReplayMetrics,
) -> bool:
    return (
        calibration_not_worse
        and baseline.run_count > 0
        and candidate.run_count == baseline.run_count
        and candidate.first_pass_rate > baseline.first_pass_rate
    )


def _rate(metrics: ReplayMetrics) -> str:
    if not metrics.run_count:
        return "not measured"
    return f"{metrics.first_pass_count}/{metrics.run_count} ({metrics.first_pass_rate:.0%})"


def _performance_table(history: dict[str, Any]) -> list[str]:
    real_rows = [
        row for row in history["version_metrics"] if row["mode"] == "real"
    ]
    mock_rows = [
        row for row in history["version_metrics"] if row["mode"] == "mock"
    ]
    lines = [
        "## Observed first-pass performance and retries",
        "",
        "| Data type | Prompt version | Runs | First-pass rate | Total retries |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for label, rows in (("Real provider", real_rows), ("Mock (not real)", mock_rows)):
        for row in rows:
            rate = (
                f"{row['first_pass_count']}/{row['run_count']} "
                f"({row['first_pass_count'] / row['run_count']:.0%})"
                if row["run_count"]
                else "not measured"
            )
            lines.append(
                f"| {label} | `{row['prompt_version']}` | {row['run_count']} | "
                f"{rate} | {row['total_retries']} |"
            )
    if not real_rows:
        lines.append(
            "| Real provider | — | 0 | not measured (no live run history) | 0 |"
        )
    if not mock_rows:
        lines.append("| Mock (not real) | — | 0 | not measured | 0 |")
    lines.append("")
    return lines


def _build_report(
    *,
    active: PromptSpec,
    history: dict[str, Any],
    calibration: dict[str, Any],
    candidate: PromptSpec | None,
    decision: str,
    baseline_replay: ReplayMetrics | None,
    candidate_replay: ReplayMetrics | None,
    replay_error: str | None,
    live_ready: bool,
) -> str:
    lines = [
        "# Prompt Evolution Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Active prompt: `{active.version}` (`{active.path.name}`)",
        f"- Chronic failure threshold: at least {CHRONIC_FAILURE_MIN_RUNS} "
        "distinct non-mock runs for one check and rubric version.",
        "- Threshold rationale: three independent real runs reduce the chance "
        "that one injected flaw, transient response, or single unusual lesson "
        "drives a persistent prompt change.",
        "",
    ]
    lines.extend(_performance_table(history))
    lines.extend(
        [
            "## Chronic failures",
            "",
        ]
    )
    if not history["chronic_failures"]:
        lines.append(
            "No hard check reached the chronic-failure threshold in real runs."
        )
    else:
        lines.extend(
            [
                "| Check | Rubric | Distinct real runs | Latest reason |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for failure in history["chronic_failures"]:
            reason = " ".join(failure["latest_reason"].split())[:220]
            lines.append(
                f"| `{failure['check_id']}` | `{failure['rubric_version']}` | "
                f"{failure['distinct_run_count']} | {reason} |"
            )

    lines.extend(
        [
            "",
            "## Calibration gate",
            "",
            f"- Deterministic mock suite: **{'PASS' if calibration['passed'] else 'FAIL'}** "
            f"({calibration['good_passed']}/{calibration['good_total']} good lessons "
            f"pass; {calibration['caught_flaws']}/{calibration['expected_flaws']} "
            f"expected flaw checks caught; {calibration['exact_checks']}/"
            f"{calibration['total_checks']} per-check outcomes match).",
            "- Any candidate changes only generator instructions, not rubric v1. "
            "The same evaluator contract and fixture suite must remain fully passing.",
            "",
            "## Paired replay gate",
            "",
        ]
    )
    if replay_error:
        lines.append(f"- Replay did not complete: {replay_error}")
    elif baseline_replay and candidate_replay:
        lines.extend(
            [
                f"- Baseline `{baseline_replay.prompt_version}`: "
                f"first-pass {_rate(baseline_replay)}; "
                f"{baseline_replay.retry_count} total retries.",
                f"- Candidate `{candidate_replay.prompt_version}`: "
                f"first-pass {_rate(candidate_replay)}; "
                f"{candidate_replay.retry_count} total retries.",
            ]
        )
    else:
        replay_blockers = []
        if not live_ready:
            replay_blockers.append("live provider settings are not enabled")
        if len(_eligible_replay_topics(history)) < MIN_REPLAY_TOPICS:
            replay_blockers.append(
                f"fewer than {MIN_REPLAY_TOPICS} eligible prior RAG topics"
            )
        lines.append(
            "- Not run: "
            + "; ".join(replay_blockers)
            + f". Found {history['real_run_count']} real run(s) and "
            + f"{len(_eligible_replay_topics(history))} eligible topic(s)."
        )

    lines.extend(
        [
            "",
            "## Candidate and decision",
            "",
            f"- Candidate: `{candidate.path.name}` (`{candidate.version}`)"
            if candidate
            else "- Candidate: not generated.",
            f"- Decision: **{decision}**.",
        ]
    )
    if history["version_metrics"]:
        lines.extend(
            [
                "",
                "## Data labels and limits",
                "",
                "Mock history is shown separately and is never counted toward "
                "the chronic-failure threshold or described as real-provider "
                "evidence. Run-history rates are descriptive, not paired "
                "counterfactuals; only the paired replay can justify adoption.",
                "The local evaluator's cited facts cover RAG. Non-RAG topics "
                "are not eligible for prompt replay until matching reviewed "
                "source facts are added.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Data labels and limits",
                "",
                "No completed run history is available. Mock outcomes, when "
                "present, are not treated as real-provider evidence.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _append_changelog(
    path: Path,
    *,
    active: PromptSpec,
    candidate: PromptSpec | None,
    decision: str,
    chronic_failures: list[dict[str, Any]],
    replay_summary: str,
    real_run_count: int,
    mock_runs: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).date().isoformat()
    evidence = (
        ", ".join(
            f"{item['check_id']} in {item['distinct_run_count']} distinct real run(s)"
            for item in chronic_failures
        )
        or "no check reached the chronic threshold"
    )
    candidate_line = (
        f"- Candidate: `{candidate.path.name}` ({candidate.version})."
        if candidate
        else "- Candidate: not created."
    )
    entry = "\n".join(
        [
            f"\n## {date} - Prompt evolution review",
            "",
            f"- Active prompt: `{active.version}`.",
            f"- Real runs in history: {real_run_count}; mock runs: {mock_runs} "
            "(mock data is not real evidence).",
            f"- Chronic-failure evidence: {evidence}.",
            candidate_line,
            f"- Replay: {replay_summary}.",
            f"- Decision: {decision}.",
            "",
        ]
    )
    if not path.exists():
        path.write_text("# Changelog\n" + entry, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8", newline="\n") as changelog:
            changelog.write(entry)


def run_evolution(
    memory: MemoryStore,
    settings: Settings,
    *,
    report_path: str | Path = DEFAULT_EVOLUTION_REPORT,
    changelog_path: str | Path = DEFAULT_CHANGELOG,
) -> EvolutionResult:
    """Propose, replay, and adopt a prompt only when all evidence gates pass."""
    active = get_active_prompt()
    rubric_version = load_rubric().version
    history = memory.evolution_snapshot(
        rubric_version,
        chronic_run_threshold=CHRONIC_FAILURE_MIN_RUNS,
    )
    calibration = _calibration_summary()
    candidate: PromptSpec | None = None
    baseline_replay: ReplayMetrics | None = None
    candidate_replay: ReplayMetrics | None = None
    replay_error: str | None = None
    adopted = False

    live_ready = bool(
        not settings.mock_llm
        and settings.api_key
        and settings.gen_model
        and settings.judge_model
    )
    if not history["chronic_failures"]:
        decision = (
            "not proposed: no check failed in three distinct real runs; "
            "the available mock history includes an injected flaw"
        )
    else:
        candidate = _create_candidate(
            active,
            history["chronic_failures"],
            history["effective_fixes"],
        )
        topics = _eligible_replay_topics(history)
        if not live_ready:
            decision = (
                "candidate retained but not adopted: live provider settings are "
                "not enabled, so a real paired replay cannot be measured"
            )
        elif len(topics) < MIN_REPLAY_TOPICS:
            decision = (
                "candidate retained but not adopted: the real run history has "
                f"fewer than {MIN_REPLAY_TOPICS} distinct RAG replay topics"
            )
        elif not calibration["passed"]:
            decision = (
                "candidate rejected: the unchanged deterministic calibration "
                "suite is not fully passing"
            )
        else:
            try:
                baseline_replay, candidate_replay = _run_prompt_replay(
                    active,
                    candidate,
                    topics,
                    settings,
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
                replay_error = f"{type(error).__name__}: {error}"
                decision = "candidate retained but not adopted: paired replay failed"
            else:
                adopted = _adoption_allowed(
                    calibration_not_worse=calibration["passed"],
                    baseline=baseline_replay,
                    candidate=candidate_replay,
                )
                if adopted:
                    activate_prompt(candidate)
                    decision = (
                        "adopted: calibration did not regress and paired real "
                        "first-pass rate improved"
                    )
                else:
                    decision = (
                        "candidate rejected: calibration and strict first-pass "
                        "improvement requirements were not both satisfied"
                    )

    metrics = history["version_metrics"]
    mock_run_count = sum(
        row["run_count"] for row in metrics if row["mode"] == "mock"
    )
    replay_summary = (
        f"{_rate(baseline_replay)} to {_rate(candidate_replay)} in paired replay"
        if baseline_replay and candidate_replay
        else "not measured"
    )
    report = _build_report(
        active=active,
        history=history,
        calibration=calibration,
        candidate=candidate,
        decision=decision,
        baseline_replay=baseline_replay,
        candidate_replay=candidate_replay,
        replay_error=replay_error,
        live_ready=live_ready,
    )
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(report, encoding="utf-8")
    _append_changelog(
        Path(changelog_path),
        active=active,
        candidate=candidate,
        decision=decision,
        chronic_failures=history["chronic_failures"],
        replay_summary=replay_summary,
        real_run_count=history["real_run_count"],
        mock_runs=mock_run_count,
    )
    return EvolutionResult(
        report_path=report_file,
        decision=decision,
        adopted=adopted,
        candidate_path=candidate.path if candidate else None,
    )
