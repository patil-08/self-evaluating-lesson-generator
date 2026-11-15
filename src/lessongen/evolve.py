"""Evidence-gated prompt proposals and replay-based adoption."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lessongen.config import (
    CHRONIC_FAILURE_MIN_RUNS,
    MAX_RETRIES,
    MIN_REPLAY_TOPICS,
    ROOT,
    Settings,
    load_config,
)
from lessongen.evaluator import load_rubric
from lessongen.graph import build
from lessongen.llm import LLMClient
from lessongen.memory import database_path, evolution_context
from lessongen.calibration import run_calibration


def _active_prompt(prompt_dir: Path) -> tuple[Path, str]:
    versions = sorted(
        prompt_dir.glob("generator_guidelines_v*.txt"),
        key=lambda item: int(item.stem.rsplit("_v", 1)[1]),
    )
    if not versions:
        raise FileNotFoundError(f"No active generator prompt found in {prompt_dir}.")
    current = versions[-1]
    return current, current.read_text(encoding="utf-8")


def _propose_prompt(
    current_prompt: str,
    chronic_failures: list[dict[str, Any]],
    prompt_dir: Path,
) -> tuple[Path, int]:
    rubric_checks = {
        check["id"]: check for check in load_rubric()["checks"]
    }
    additions = []
    for failure in chronic_failures:
        check = rubric_checks.get(failure["check_id"])
        if check is None:
            raise ValueError(f"No rubric guidance exists for {failure['check_id']}.")
        examples = "; ".join(check["fail_examples"])
        additions.append(
            f"- For check {failure['check_id']}, meet this criterion: "
            f"{check['pass_criteria']} Avoid these known failure patterns: {examples}"
        )
    candidate_text = (
        current_prompt.rstrip()
        + "\n\n# Proposed evidence-based refinements\n"
        + "\n".join(additions)
        + "\n"
    )

    existing_versions = []
    for path in prompt_dir.glob("generator*_v*.txt"):
        suffix = path.stem.rsplit("_v", 1)[-1]
        if suffix.isdigit():
            existing_versions.append(int(suffix))
    for path in prompt_dir.glob("generator_v*.txt"):
        suffix = path.stem.removeprefix("generator_v")
        if suffix.isdigit():
            existing_versions.append(int(suffix))
    version = max(existing_versions, default=1) + 1
    candidate = prompt_dir / f"generator_v{version}.txt"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    with candidate.open("x", encoding="utf-8") as file:
        file.write(candidate_text)
    return candidate, version


def _calibration_metrics() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lessongen-calibration-") as directory:
        results, _ = run_calibration(
            output_path=Path(directory) / "calibration.md"
        )
    exact_matches = sum(
        item.failed_checks == item.fixture.expected_failures for item in results
    )
    return {
        "mode": "mock calibration",
        "fixture_count": len(results),
        "exact_matches": exact_matches,
        "mismatches": len(results) - exact_matches,
    }


def _replay(
    client: LLMClient,
    topics: list[str],
    prompt: str,
    version: str,
    memory_path: str | Path | None,
) -> dict[str, Any]:
    workflow = build(
        client=client,
        max_retries=MAX_RETRIES,
        generator_prompt_override=prompt,
        prompt_version_override=version,
        memory_path=str(memory_path) if memory_path is not None else None,
    )
    attempts = [workflow.invoke({"topic": topic}) for topic in topics]
    first_pass_count = sum(
        result["attempt_results"][0]["passed"] for result in attempts
    )
    retry_count = sum(result["attempt_count"] - 1 for result in attempts)
    return {
        "run_count": len(attempts),
        "first_pass_count": first_pass_count,
        "first_pass_rate": first_pass_count / len(attempts) if attempts else None,
        "retry_count": retry_count,
        "statuses": [result["status"] for result in attempts],
    }


def _render_report(decision: dict[str, Any]) -> str:
    history = decision["real_history"]
    before = decision.get("replay_before")
    after = decision.get("replay_after")
    lines = [
        f"## Evolution evaluation — {decision['timestamp']}",
        "",
        f"- **Decision:** {decision['decision']}",
        f"- **Replay mode:** {decision['replay_mode']}",
        f"- **Candidate prompt:** {decision.get('candidate_prompt') or 'not created'}",
        f"- **Rubric candidate:** {decision.get('rubric_candidate') or 'none'}",
        f"- **Chronic-failure threshold:** {decision['min_chronic_runs']} distinct real runs",
        f"- **Replay-topic minimum:** {decision['min_replay_topics']} distinct topics",
        "",
        "### Chronic failures from real history",
        "",
    ]
    if history["chronic_failures"]:
        for failure in history["chronic_failures"]:
            lines.append(
                f"- `{failure['check_id']}` failed in {failure['run_count']} distinct runs."
            )
    else:
        lines.append("- No chronic real-run failure met the threshold.")
    lines.extend(
        [
            "",
            "### Recorded production history (real runs only)",
            "",
            f"- Runs: {history['real_run_count']}",
            (
                f"- First-pass rate: {history['first_pass_count']}/"
                f"{history['real_run_count']} ({history['first_pass_rate']:.1%})"
                if history["first_pass_rate"] is not None
                else "- First-pass rate: n/a (no recorded real runs)"
            ),
            f"- Total retries: {history['retry_count']}",
            "",
            "### Candidate replay comparison",
            "",
            "| Replay | First-pass rate | Retries | Runs |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    if before and after:
        for label, metrics in (
            ("Current prompt (before)", before),
            ("Candidate prompt (after)", after),
        ):
            rate = (
                f"{metrics['first_pass_count']}/{metrics['run_count']} "
                f"({metrics['first_pass_rate']:.1%})"
                if metrics["first_pass_rate"] is not None
                else "n/a"
            )
            lines.append(
                f"| {label} | {rate} | {metrics['retry_count']} | {metrics['run_count']} |"
            )
    else:
        lines.append("| Replay not run | n/a | n/a | n/a |")
    calibration_before = decision.get("calibration_before")
    calibration_after = decision.get("calibration_after")
    lines.extend(
        [
            "",
            "### Calibration guard (mock fixtures)",
            "",
            "| Version | Exact fixture matches | Mismatches | Fixtures |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for label, metrics in (
        ("Before", calibration_before),
        ("After", calibration_after),
    ):
        if metrics:
            lines.append(
                f"| {label} ({metrics['mode']}) | {metrics['exact_matches']} | "
                f"{metrics['mismatches']} | {metrics['fixture_count']} |"
            )
    lines.extend(
        [
            "",
            (
                f"- Calibration gate: **{'PASS' if decision['calibration_gate'] else 'FAIL'}**."
                if calibration_after
                else "- Calibration gate: **NOT RUN**."
            ),
            (
                f"- First-pass improvement gate: **{'PASS' if decision['replay_gate'] else 'FAIL'}**."
                if after
                else "- First-pass improvement gate: **NOT RUN**."
            ),
            "",
            "Mock replay results are explicitly labeled and never authorize adoption. "
            "No rubric change was proposed; rubric version remains unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    *,
    settings: Settings | None = None,
    client: LLMClient | None = None,
    min_runs: int = CHRONIC_FAILURE_MIN_RUNS,
    replay_topics: int = MIN_REPLAY_TOPICS,
    db_path: str | Path | None = None,
    root: str | Path = ROOT,
    report_path: str | Path | None = None,
    decision_log_path: str | Path | None = None,
) -> dict[str, Any]:
    """Propose, replay, and adopt a prompt only when both gates pass."""
    if min_runs < 1:
        raise ValueError("min_runs must be at least one.")
    if replay_topics < 1:
        raise ValueError("replay_topics must be at least one.")
    project_root = Path(root)
    prompt_dir = project_root / "prompts"
    active_path, active_text = _active_prompt(prompt_dir)
    history = evolution_context(
        min_runs=min_runs,
        replay_topics=replay_topics,
        path=db_path,
    )
    current_calibration = _calibration_metrics()
    decision: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": "INELIGIBLE",
        "replay_mode": "not run",
        "min_chronic_runs": min_runs,
        "min_replay_topics": replay_topics,
        "active_prompt": active_path.name,
        "candidate_prompt": None,
        "rubric_candidate": None,
        "real_history": history,
        "calibration_before": current_calibration,
        "calibration_after": None,
        "calibration_gate": None,
        "replay_before": None,
        "replay_after": None,
        "replay_gate": None,
        "adopted_prompt": None,
    }

    if not history["chronic_failures"]:
        decision["reason"] = (
            f"No check failed across {min_runs} distinct recorded real runs."
        )
    elif len(history["topics"]) < replay_topics:
        decision["reason"] = (
            f"Only {len(history['topics'])} distinct real topic(s) are available; "
            f"{replay_topics} are required."
        )
    else:
        candidate_path, candidate_version = _propose_prompt(
            active_text,
            history["chronic_failures"],
            prompt_dir,
        )
        decision["candidate_prompt"] = str(candidate_path)
        actual_client = client or LLMClient(settings=settings or load_config())
        decision["replay_mode"] = "mock" if actual_client.settings.mock_llm else "real"
        current_metrics = _replay(
            actual_client,
            history["topics"],
            active_text,
            active_path.stem,
            db_path,
        )
        candidate_text = candidate_path.read_text(encoding="utf-8")
        candidate_metrics = _replay(
            actual_client,
            history["topics"],
            candidate_text,
            f"generator_v{candidate_version}",
            db_path,
        )
        decision["replay_before"] = current_metrics
        decision["replay_after"] = candidate_metrics
        baseline_calibration = _calibration_metrics()
        candidate_calibration = _calibration_metrics()
        decision["calibration_before"] = baseline_calibration
        decision["calibration_after"] = candidate_calibration
        decision["calibration_gate"] = (
            candidate_calibration["mismatches"] <= baseline_calibration["mismatches"]
            and candidate_calibration["exact_matches"] >= baseline_calibration["exact_matches"]
        )
        decision["replay_gate"] = (
            candidate_metrics["first_pass_rate"] is not None
            and current_metrics["first_pass_rate"] is not None
            and candidate_metrics["first_pass_rate"] > current_metrics["first_pass_rate"]
        )
        real_replay = decision["replay_mode"] == "real"
        if decision["calibration_gate"] and decision["replay_gate"] and real_replay:
            active_candidate = prompt_dir / f"generator_guidelines_v{candidate_version}.txt"
            with active_candidate.open("x", encoding="utf-8") as file:
                file.write(candidate_text)
            decision["decision"] = "ADOPTED"
            decision["adopted_prompt"] = str(active_candidate)
            decision["reason"] = (
                "Calibration did not regress and the real replay first-pass rate improved."
            )
        else:
            decision["decision"] = "REJECTED"
            decision["reason"] = (
                "Candidate was not adopted: it must pass both gates using real replay results."
            )

    decision["markdown"] = _render_report(decision)
    output_report = Path(report_path) if report_path else project_root / "docs" / "evolution_report.md"
    output_report.parent.mkdir(parents=True, exist_ok=True)
    with output_report.open("a", encoding="utf-8") as file:
        file.write(decision["markdown"])
    output_log = (
        Path(decision_log_path)
        if decision_log_path
        else (Path(db_path) if db_path else database_path()).parent / "evolution_decisions.jsonl"
    )
    output_log.parent.mkdir(parents=True, exist_ok=True)
    with output_log.open("a", encoding="utf-8") as file:
        file.write(json.dumps({key: value for key, value in decision.items() if key != "markdown"}) + "\n")
    return decision
