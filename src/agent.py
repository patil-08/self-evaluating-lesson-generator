"""Bounded LangGraph workflow for generating and checking beginner lessons."""

from __future__ import annotations

import difflib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.config import MAX_RETRIES, Settings, load_config
from src.evaluator import EvaluationResult, evaluate_lesson
from src.llm import LLMClient, ModelRole, UsageSnapshot
from src.rubric import load_rubric
from src.sources import Fact, load_facts

ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = "1.0"
PROMPT_PATH = ROOT / "prompts" / "lesson_generation_v1.txt"
DEFAULT_LEARNER_PROFILE = (
    "A 12th-grade graduate in India with limited English vocabulary, a "
    "non-English-medium background, and no technical background who wants "
    "to start an AI career."
)
_INJECTABLE_ERRORS = {
    "false_claim",
    "jargon",
    "no_example",
    "bad_order",
    "long_sentences",
}


class CheckRecord(TypedDict):
    check_id: str
    dimension: str
    passed: bool
    reason: str
    evidence_quote: str
    fix_instruction: str


class AttemptRecord(TypedDict, total=False):
    attempt: int
    status: str
    passed_checks: int
    total_checks: int
    failed_checks: list[CheckRecord]
    all_checks: list[dict[str, Any]]
    usage: dict[str, int | float]
    requested_fixes: list[str]
    changes_on_retry: dict[str, Any] | None


class LessonState(TypedDict, total=False):
    run_id: str
    topic: str
    learner_profile: str
    max_retries: int
    injected_error: str | None
    attempt: int
    outline: list[dict[str, Any]]
    source_facts: list[dict[str, str]]
    rubric_version: str
    prompt_version: str
    model_names: dict[str, str]
    lesson: str
    attempts: list[AttemptRecord]
    rejection_log: list[AttemptRecord]
    feedback: list[dict[str, str]]
    attempt_usage_start: dict[str, int | float]
    best_draft: str | None
    best_draft_score: int
    best_draft_attempt: int | None
    current_passed: bool
    next_route: str
    status: str
    final_lesson: str | None
    usage: dict[str, int | float]
    output_json: str
    output_markdown: str


@dataclass(frozen=True)
class AgentRunResult:
    """Final graph state and paths to the durable run report."""

    state: LessonState
    json_path: Path
    markdown_path: Path


def _usage_dict(snapshot: UsageSnapshot) -> dict[str, int | float]:
    return {
        "calls": snapshot.calls,
        "prompt_tokens": snapshot.prompt_tokens,
        "completion_tokens": snapshot.completion_tokens,
        "total_tokens": snapshot.total_tokens,
        "latency_ms": round(snapshot.latency_ms, 3),
    }


def _usage_delta(
    current: UsageSnapshot,
    start: dict[str, int | float],
) -> dict[str, int | float]:
    current_values = _usage_dict(current)
    return {
        key: (
            round(float(current_values[key]) - float(start[key]), 3)
            if key == "latency_ms"
            else int(current_values[key]) - int(start[key])
        )
        for key in current_values
    }


def _model_names(client: LLMClient) -> dict[str, str]:
    settings = client.settings
    return {
        "generation": settings.gen_model if not settings.mock_llm else "mock-generation",
        "judge": settings.judge_model if not settings.mock_llm else "mock-judge",
    }


def _make_outline(topic: str, facts: list[Fact]) -> list[dict[str, Any]]:
    fact_ids = {fact.id for fact in facts}
    sections = [
        {
            "heading": "What is RAG?",
            "learning_goal": f"Explain {topic} in one plain-language definition.",
            "source_ids": ["F01", "F02"],
        },
        {
            "heading": "How does RAG work?",
            "learning_goal": (
                "Explain search, adding found text to the question, and answer "
                "writing; briefly define chunks, embeddings, and vector search."
            ),
            "source_ids": ["F04", "F05", "F06", "F07", "F09", "F10"],
        },
        {
            "heading": "Everyday worked example",
            "learning_goal": (
                "Walk through a familiar example in at least three ordered steps."
            ),
            "source_ids": ["F18"],
        },
        {
            "heading": "Why does RAG matter?",
            "learning_goal": (
                "Explain the value of using supplied, private, or recent "
                "information and the limits of that value."
            ),
            "source_ids": ["F03", "F11", "F12", "F13"],
        },
        {
            "heading": "Mini glossary",
            "learning_goal": "Define RAG, retrieval, embedding, vector database, and language model.",
            "source_ids": ["F01", "F04", "F07", "F09"],
        },
        {
            "heading": "Limits",
            "learning_goal": "State that RAG can still return a wrong answer.",
            "source_ids": ["F13"],
        },
    ]
    return [
        {
            **section,
            "source_ids": [
                fact_id for fact_id in section["source_ids"] if fact_id in fact_ids
            ],
        }
        for section in sections
    ]


def _generation_prompt(state: LessonState) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    context = {
        "topic": state["topic"],
        "learner_profile": state["learner_profile"],
        "outline": state["outline"],
        "source_facts": state["source_facts"],
        "attempt": state["attempt"] + 1,
        "max_retries": state["max_retries"],
        "previous_lesson": state.get("lesson", ""),
        "retry_feedback": state.get("feedback", []),
    }
    return f"{template}\n\nGeneration context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"


def _inject_error(lesson: str, error_name: str | None) -> str:
    if error_name is None:
        return lesson
    if error_name == "false_claim":
        return lesson.rstrip() + "\n\nRAG guarantees a correct answer every time.\n"
    if error_name == "jargon":
        return lesson.rstrip() + "\n\nCosine similarity ranks the results.\n"
    if error_name == "long_sentences":
        sentence = (
            "This method can help because the system searches information supplied "
            "by a person before it writes an answer, and that answer can use details "
            "from the selected notes when they match the question being asked."
        )
        return lesson.rstrip() + "\n\n" + sentence + "\n"
    if error_name == "no_example":
        return re.sub(
            r"(?ms)^## Everyday worked example\s*\n.*?(?=^## |\Z)",
            "",
            lesson,
            count=1,
        )
    if error_name == "bad_order":
        heading_pattern = re.compile(r"(?m)^## .+$")
        headings = list(heading_pattern.finditer(lesson))
        blocks: list[tuple[str, str]] = []
        prefix = lesson[: headings[0].start()] if headings else ""
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(lesson)
            blocks.append((match.group(0), lesson[match.start() : end]))
        how = next((i for i, (heading, _) in enumerate(blocks) if heading == "## How does RAG work?"), None)
        why = next((i for i, (heading, _) in enumerate(blocks) if heading == "## Why does RAG matter?"), None)
        if how is not None and why is not None:
            blocks[how], blocks[why] = blocks[why], blocks[how]
            return prefix + "".join(block for _, block in blocks)
    raise ValueError(f"Unsupported injected error: {error_name!r}.")


def _fix_instruction(check: dict[str, Any]) -> str:
    check_id = check["check_id"]
    instructions = {
        "ACC-01": "Remove or correct every unsupported claim using only the supplied source facts.",
        "COVER-01": "Order the sections as what RAG is, how it works, then why it matters.",
        "BEGIN-01": "Rewrite dense or assumed technical explanations in direct language for this learner.",
        "BEGIN-02": "Split long sentences into short sentences while preserving their meaning.",
        "BEGIN-03": "Replace dense wording with familiar, shorter words and sentence structures.",
        "BEGIN-04": "Replace each flagged difficult word with a common word that keeps the meaning.",
        "STYLE-01": "Remove idioms and reduce phrasal verbs; use direct verbs.",
        "JARG-01": "Define each technical term in plain words at its first use.",
        "JARG-02": "Replace or define the unexplained specialized term near its first use.",
        "GLOSS-01": "Add the mini glossary with all five required terms and plain definitions.",
        "EXAMPLE-01": "Add a familiar everyday situation and explain how it relates to RAG.",
        "EXAMPLE-02": "Show at least three ordered actions in the example.",
        "EXAMPLE-03": "Connect the example to finding text, adding it to the question, and writing an answer.",
        "COVER-02": "Explain what RAG is, why it is useful, and each of its three main steps.",
        "LIMIT-01": "Add a clear limitation: retrieval can fail and RAG does not guarantee correctness.",
        "LENGTH-01": "Keep the complete lesson within the required word-count range.",
    }
    return instructions.get(
        check_id,
        f"Revise the lesson to satisfy the failed hard check {check_id}.",
    )


def _serialize_evaluation(result: EvaluationResult) -> list[dict[str, Any]]:
    return [
        {
            "check_id": check.check_id,
            "dimension": check.dimension,
            "type": check.check_type,
            "passed": check.passed,
            "reason": check.reason,
            "evidence_quote": check.evidence_quote,
        }
        for check in result.checks
    ]


def _changes_summary(before: str, after: str) -> dict[str, Any]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    removed = 0
    added = 0
    removed_examples: list[str] = []
    added_examples: list[str] = []
    for tag, start_a, end_a, start_b, end_b in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed += end_a - start_a
            removed_examples.extend(
                line.strip()[:240]
                for line in before_lines[start_a:end_a]
                if line.strip()
            )
        if tag in {"replace", "insert"}:
            added += end_b - start_b
            added_examples.extend(
                line.strip()[:240]
                for line in after_lines[start_b:end_b]
                if line.strip()
            )
    return {
        "before_word_count": len(before.split()),
        "after_word_count": len(after.split()),
        "lines_removed_or_replaced": removed,
        "lines_added_or_replaced": added,
        "removed_examples": removed_examples[:3],
        "added_examples": added_examples[:3],
    }


def _replace_attempt(
    attempts: list[AttemptRecord],
    attempt_number: int,
    updates: dict[str, Any],
) -> list[AttemptRecord]:
    return [
        {**record, **updates} if record["attempt"] == attempt_number else record
        for record in attempts
    ]


def build_lesson_graph(
    client: LLMClient,
    *,
    max_retries: int = MAX_RETRIES,
    inject_error: str | None = None,
):
    """Compile the explicit plan/generate/evaluate/route LangGraph."""
    if not 0 <= max_retries <= MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}.")
    if inject_error not in _INJECTABLE_ERRORS | {None}:
        raise ValueError(f"Unsupported injected error: {inject_error!r}.")

    def plan_node(state: LessonState) -> dict[str, Any]:
        facts = load_facts()
        outline = _make_outline(state["topic"], facts)
        source_facts = [
            {
                "id": fact.id,
                "fact": fact.fact,
                "source_url": fact.source_url,
            }
            for fact in facts
        ]
        return {
            "outline": outline,
            "source_facts": source_facts,
            "rubric_version": load_rubric().version,
            "prompt_version": PROMPT_VERSION,
            "model_names": _model_names(client),
        }

    def generate_node(state: LessonState) -> dict[str, Any]:
        next_attempt = state["attempt"] + 1
        usage_start = _usage_dict(client.usage)
        prompt = _generation_prompt(state)
        response = client.complete(
            prompt,
            role=ModelRole.GENERATION,
            system_prompt=(
                "You write accurate, source-grounded beginner lessons. Follow "
                "the requested structure, use short plain sentences, and obey "
                "all retry instructions. Return only the lesson in Markdown."
            ),
            temperature=0.2,
        )
        lesson = response.content.strip()
        if next_attempt == 1 and inject_error is not None:
            lesson = _inject_error(lesson, inject_error)

        updates: dict[str, Any] = {
            "attempt": next_attempt,
            "lesson": lesson,
            "attempt_usage_start": usage_start,
        }
        if next_attempt > 1:
            previous_attempt = next_attempt - 1
            change_summary = _changes_summary(state.get("lesson", ""), lesson)
            updates["attempts"] = _replace_attempt(
                state.get("attempts", []),
                previous_attempt,
                {"changes_on_retry": change_summary},
            )
            updates["rejection_log"] = _replace_attempt(
                state.get("rejection_log", []),
                previous_attempt,
                {"changes_on_retry": change_summary},
            )
        return updates

    def evaluate_node(state: LessonState) -> dict[str, Any]:
        result = evaluate_lesson(state["lesson"], client=client)
        all_checks = _serialize_evaluation(result)
        failed_checks: list[CheckRecord] = []
        for check in all_checks:
            if check["passed"]:
                continue
            failed_checks.append(
                {
                    "check_id": check["check_id"],
                    "dimension": check["dimension"],
                    "passed": False,
                    "reason": check["reason"],
                    "evidence_quote": check["evidence_quote"],
                    "fix_instruction": _fix_instruction(check),
                }
            )
        usage = _usage_delta(client.usage, state["attempt_usage_start"])
        passed_count = len(all_checks) - len(failed_checks)
        record: AttemptRecord = {
            "attempt": state["attempt"],
            "status": "passed" if result.passed else "rejected",
            "passed_checks": passed_count,
            "total_checks": len(all_checks),
            "failed_checks": failed_checks,
            "all_checks": all_checks,
            "usage": usage,
            "requested_fixes": [],
            "changes_on_retry": None,
        }
        attempts = [*state.get("attempts", []), record]
        rejections = list(state.get("rejection_log", []))
        if not result.passed:
            rejections.append(record)

        best_draft = state.get("best_draft")
        best_score = state.get("best_draft_score", -1)
        best_attempt = state.get("best_draft_attempt")
        if passed_count > best_score:
            best_draft = state["lesson"]
            best_score = passed_count
            best_attempt = state["attempt"]
        return {
            "attempts": attempts,
            "rejection_log": rejections,
            "current_passed": result.passed,
            "best_draft": best_draft,
            "best_draft_score": best_score,
            "best_draft_attempt": best_attempt,
            "usage": _usage_dict(client.usage),
        }

    def route_node(state: LessonState) -> dict[str, str]:
        if state["current_passed"]:
            return {"next_route": "ship"}
        if state["attempt"] <= state["max_retries"]:
            return {"next_route": "regenerate"}
        return {"next_route": "escalate_to_human"}

    def regenerate_node(state: LessonState) -> dict[str, Any]:
        latest_rejection = state["rejection_log"][-1]
        failed_checks = latest_rejection["failed_checks"]
        feedback = [
            {
                "check_id": check["check_id"],
                "reason": check["reason"],
                "evidence": check["evidence_quote"],
                "fix_instruction": check["fix_instruction"],
            }
            for check in failed_checks
        ]
        requested_fixes = [item["fix_instruction"] for item in feedback]
        attempt_number = latest_rejection["attempt"]
        return {
            "feedback": feedback,
            "attempts": _replace_attempt(
                state["attempts"],
                attempt_number,
                {"requested_fixes": requested_fixes},
            ),
            "rejection_log": _replace_attempt(
                state["rejection_log"],
                attempt_number,
                {"requested_fixes": requested_fixes},
            ),
        }

    def ship_node(state: LessonState) -> dict[str, Any]:
        return {
            "status": "passed",
            "final_lesson": state["lesson"],
            "usage": _usage_dict(client.usage),
        }

    def escalate_node(state: LessonState) -> dict[str, Any]:
        return {
            "status": "escalated_to_human",
            "final_lesson": None,
            "best_draft": state.get("best_draft"),
            "usage": _usage_dict(client.usage),
        }

    graph = StateGraph(LessonState)
    graph.add_node("plan", plan_node)
    graph.add_node("generate", generate_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("route", route_node)
    graph.add_node("regenerate", regenerate_node)
    graph.add_node("ship", ship_node)
    graph.add_node("escalate_to_human", escalate_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "generate")
    graph.add_edge("generate", "evaluate")
    graph.add_edge("evaluate", "route")
    graph.add_conditional_edges(
        "route",
        lambda state: state["next_route"],
        {
            "ship": "ship",
            "regenerate": "regenerate",
            "escalate_to_human": "escalate_to_human",
        },
    )
    graph.add_edge("regenerate", "generate")
    graph.add_edge("ship", END)
    graph.add_edge("escalate_to_human", END)
    return graph.compile()


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Lesson run: {report['topic']}",
        "",
        f"- **Run ID:** `{report['run_id']}`",
        f"- **Final status:** `{report['final_status']}`",
        f"- **Attempts:** {len(report['attempts'])}",
        f"- **Prompt version:** {report['prompt_version']}",
        f"- **Rubric version:** {report['rubric_version']}",
        f"- **Generation model:** `{report['models']['generation']}`",
        f"- **Judge model:** `{report['models']['judge']}`",
        f"- **Usage:** {report['usage']['total_tokens']} tokens; "
        f"{report['usage']['latency_ms']} ms across {report['usage']['calls']} calls",
        "",
        "## Rejection log",
        "",
    ]
    if not report["rejection_log"]:
        lines.append("No rejected drafts.")
    for rejected in report["rejection_log"]:
        lines.extend(
            [
                f"### Attempt {rejected['attempt']}",
                "",
            ]
        )
        for failure in rejected["failed_checks"]:
            lines.extend(
                [
                    f"- **{failure['check_id']} — {failure['dimension']}**",
                    f"  - Why: {failure['reason']}",
                    f"  - Evidence: {failure['evidence_quote'] or '(omission)'}",
                    f"  - Requested fix: {failure['fix_instruction']}",
                ]
            )
        if rejected.get("changes_on_retry"):
            changes = rejected["changes_on_retry"]
            lines.extend(
                [
                    f"  - Retry change: {changes['lines_removed_or_replaced']} "
                    f"lines removed/replaced and {changes['lines_added_or_replaced']} "
                    "added/replaced; word count "
                    f"{changes['before_word_count']} → {changes['after_word_count']}.",
                ]
            )
            removed_examples = changes.get("removed_examples", [])
            added_examples = changes.get("added_examples", [])
            if removed_examples:
                lines.append(
                    "  - Removed/replaced text: "
                    + " | ".join(f"`{text}`" for text in removed_examples)
                )
            if added_examples:
                lines.append(
                    "  - Added/replacement text: "
                    + " | ".join(f"`{text}`" for text in added_examples)
                )
        elif rejected.get("requested_fixes"):
            lines.append("- Retry changes: no subsequent attempt was generated.")
        lines.append("")

    if report["final_status"] == "passed":
        lines.extend(["## Passing lesson", "", report["final_lesson"] or "", ""])
    else:
        lines.extend(
            [
                "## Best draft — not approved",
                "",
                "This draft failed the hard rubric and must not be used as a passing lesson.",
                "",
                report["best_draft"] or "(No draft was generated.)",
                "",
            ]
        )
    return "\n".join(lines)


def _write_report(state: LessonState, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{state['run_id']}.json"
    markdown_path = output_dir / f"{state['run_id']}.md"
    report = {
        "run_id": state["run_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "topic": state["topic"],
        "learner_profile": state["learner_profile"],
        "final_status": state["status"],
        "prompt_version": state["prompt_version"],
        "rubric_version": state["rubric_version"],
        "models": state["model_names"],
        "usage": state["usage"],
        "attempts": state["attempts"],
        "rejection_log": state["rejection_log"],
        "final_lesson": state["final_lesson"],
        "best_draft": state["best_draft"],
        "best_draft_attempt": state["best_draft_attempt"],
    }
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def run_lesson(
    topic: str,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    max_retries: int = MAX_RETRIES,
    inject_error: str | None = None,
    output_dir: str | Path = ROOT / "outputs",
    learner_profile: str = DEFAULT_LEARNER_PROFILE,
) -> AgentRunResult:
    """Run a bounded lesson workflow and persist its JSON/Markdown report."""
    normalized_topic = topic.strip()
    if not normalized_topic:
        raise ValueError("topic must not be empty.")
    if not 0 <= max_retries <= MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}.")
    if inject_error not in _INJECTABLE_ERRORS | {None}:
        raise ValueError(f"Unsupported injected error: {inject_error!r}.")
    if client is None:
        active_settings = settings or load_config()
        client = LLMClient(settings=active_settings)

    initial_state: LessonState = {
        "run_id": uuid.uuid4().hex,
        "topic": normalized_topic,
        "learner_profile": learner_profile,
        "max_retries": max_retries,
        "injected_error": inject_error,
        "attempt": 0,
        "attempts": [],
        "rejection_log": [],
        "feedback": [],
        "best_draft": None,
        "best_draft_score": -1,
        "best_draft_attempt": None,
        "current_passed": False,
        "final_lesson": None,
        "status": "generating",
    }
    graph = build_lesson_graph(
        client,
        max_retries=max_retries,
        inject_error=inject_error,
    )
    final_state = graph.invoke(initial_state)
    json_path, markdown_path = _write_report(
        final_state,
        Path(output_dir),
    )
    final_state["output_json"] = str(json_path)
    final_state["output_markdown"] = str(markdown_path)
    return AgentRunResult(
        state=final_state,
        json_path=json_path,
        markdown_path=markdown_path,
    )
