"""Bounded LangGraph lesson workflow with explicit rejection and escalation."""

from __future__ import annotations

import difflib
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from lessongen.config import MAX_RETRIES, ROOT, Settings, load_config
from lessongen.checks_llm import JUDGE_PROMPT_PATH
from lessongen.evaluator import (
    EvaluationResult,
    evaluate_lesson,
    load_rubric,
)
from lessongen.llm import LLMClient, ModelRole, UsageSnapshot
from lessongen import memory
from lessongen.sources import Fact, load_facts

INJECTION_TYPES = ("false_claim", "jargon", "no_example", "bad_order", "long_sentences")


class CheckResult(TypedDict):
    check_id: str
    dimension: str
    check_type: str
    passed: bool
    reason: str
    evidence: str


class FeedbackItem(TypedDict):
    check_id: str
    reason: str
    evidence: str
    fix_instruction: str


class AttemptResult(TypedDict):
    attempt: int
    passed: bool
    checks: list[CheckResult]
    failed_checks: list[FeedbackItem]
    changes_from_previous: str


class AgentState(TypedDict, total=False):
    topic: str
    learner_profile: str
    sources: list[dict[str, str]]
    outline: str
    generator_guidelines: str
    memory_lessons: list[dict[str, str]]
    drafts: list[str]
    best_draft: str
    best_check_count: int
    attempt_results: list[AttemptResult]
    feedback: list[FeedbackItem]
    attempt_count: int
    max_retries: int
    inject_error: str | None
    next_step: Literal["ship", "regenerate", "escalate"]
    status: str
    lesson: str
    rubric_version: str
    prompt_versions: dict[str, str]
    model_names: dict[str, str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    execution_mode: Literal["mock", "live"]
    usage: dict[str, int | float]
    generation_memory: list[dict[str, Any]]


class GraphInputError(ValueError):
    """Raised when the requested graph run is invalid."""


def _read_generator_prompt() -> tuple[str, str]:
    prompt_dir = ROOT / "prompts"
    candidates = sorted(
        prompt_dir.glob("generator_guidelines_v*.txt"),
        key=lambda path: int(path.stem.rsplit("_v", 1)[1]),
    )
    if not candidates:
        raise FileNotFoundError(f"No generator guidelines found under {prompt_dir}.")
    prompt_path = candidates[-1]
    return prompt_path.read_text(encoding="utf-8"), prompt_path.stem.rsplit("_v", 1)[-1]


def _fact_payload(facts: list[Fact]) -> list[dict[str, str]]:
    return [
        {"fact_id": fact.id, "text": fact.text, "source_url": fact.source_url}
        for fact in facts
    ]


def _inject(lesson: str, kind: str) -> str:
    if kind == "false_claim":
        return lesson + "\n\nRAG retrains the model on your files every time you ask.\n"
    if kind == "jargon":
        return lesson + "\n\nThe system relies on HNSW and cosine similarity.\n"
    if kind == "no_example":
        return re.sub(
            r"(?ms)^## Example\s*\n.*?(?=^## |\Z)",
            "",
            lesson,
            count=1,
        )
    if kind == "bad_order":
        matches = list(re.finditer(r"(?m)^## .+$", lesson))
        sections: list[tuple[str, str]] = []
        preamble = lesson[: matches[0].start()] if matches else ""
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(lesson)
            sections.append((match.group(0), lesson[match.start():end]))
        what = next(i for i, (heading, _) in enumerate(sections) if heading.startswith("## What"))
        how = next(i for i, (heading, _) in enumerate(sections) if heading.startswith("## How"))
        sections[what], sections[how] = sections[how], sections[what]
        return preamble + "\n".join(section for _, section in sections)
    if kind == "long_sentences":
        return (
            lesson
            + "\n\nA learner can use this system to search many supplied school documents "
            "and read the results before asking a question, while the software combines "
            "the selected information with the question and then writes a response that "
            "still needs review by a person who understands the original material.\n"
        )
    raise GraphInputError(f"Unknown injected error {kind!r}.")


def _change_summary(previous: str | None, current: str) -> str:
    if previous is None:
        return "Initial draft."
    diff = list(
        difflib.unified_diff(
            previous.splitlines(),
            current.splitlines(),
            fromfile="previous",
            tofile="current",
            lineterm="",
        )
    )
    changed = [line for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    if not changed:
        return "No text changes."
    removed = sum(line.startswith("-") for line in changed)
    added = sum(line.startswith("+") for line in changed)
    examples = "; ".join(line[1:].strip() for line in changed[:3])
    return f"Removed {removed} line(s), added {added} line(s). {examples}"


def _fix_instruction(check: dict[str, Any]) -> str:
    return (
        f"Meet this pass criterion: {check['pass_criteria']} "
        "Change only what is needed and preserve sections and content that already pass."
    )


def _serialize_result(result: EvaluationResult, rubric: dict[str, Any]) -> AttemptResult:
    checks: list[CheckResult] = [
        {
            "check_id": item.check_id,
            "dimension": item.dimension,
            "check_type": item.check_type,
            "passed": item.passed,
            "reason": item.reason,
            "evidence": item.evidence_quote,
        }
        for item in result.checks
    ]
    checks_by_id = {check["id"]: check for check in rubric["checks"]}
    failed: list[FeedbackItem] = [
        {
            "check_id": item.check_id,
            "reason": item.reason,
            "evidence": item.evidence_quote,
            "fix_instruction": _fix_instruction(checks_by_id[item.check_id]),
        }
        for item in result.checks
        if not item.passed
    ]
    return {
        "attempt": 0,
        "passed": result.passed,
        "checks": checks,
        "failed_checks": failed,
        "changes_from_previous": "",
    }


def _usage_delta(current: UsageSnapshot, start: UsageSnapshot) -> dict[str, int | float]:
    prompt_tokens = current.prompt_tokens - start.prompt_tokens
    completion_tokens = current.completion_tokens - start.completion_tokens
    return {
        "calls": current.calls - start.calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": round(current.latency_ms - start.latency_ms, 2),
    }


def build(
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    max_retries: int = MAX_RETRIES,
    inject_error: str | None = None,
    evaluator_fn: Any = evaluate_lesson,
    generator_prompt_override: str | None = None,
    prompt_version_override: str | None = None,
    memory_path: str | None = None,
) -> Any:
    """Build the workflow; max_retries counts retries after the initial draft."""
    if not isinstance(max_retries, int) or isinstance(max_retries, bool):
        raise GraphInputError("max_retries must be an integer.")
    if max_retries < 0 or max_retries > MAX_RETRIES:
        raise GraphInputError(f"max_retries must be between zero and {MAX_RETRIES}.")
    if inject_error is not None and inject_error not in INJECTION_TYPES:
        raise GraphInputError(
            f"inject_error must be one of: {', '.join(INJECTION_TYPES)}."
        )
    active_client = client or LLMClient(settings=settings or load_config())
    starting_usage = active_client.usage

    def plan(state: AgentState) -> dict[str, Any]:
        facts = load_facts()
        profile = state.get(
            "learner_profile",
            "An Indian 12th-grade graduate who is new to technical subjects and prefers clear, simple English.",
        )
        outline_prompt = (
            f"Create a concise lesson outline about {state['topic']} for this learner: {profile}\n"
            "Order: definition, why it matters, how it works, worked example, limitations, recap.\n"
            "Use only these reviewed source facts:\n"
            + "\n".join(f"{fact.id}: {fact.text}" for fact in facts)
        )
        outline = active_client.complete(
            outline_prompt,
            role=ModelRole.GENERATION,
            temperature=0.0,
        ).content
        rubric = load_rubric()
        if generator_prompt_override is None:
            guidelines, generator_version = _read_generator_prompt()
        else:
            guidelines = generator_prompt_override
            generator_version = prompt_version_override or "candidate"
        memory_lessons = memory.get_generation_lessons(path=memory_path)
        return {
            "learner_profile": profile,
            "sources": _fact_payload(facts),
            "outline": outline,
            "generator_guidelines": guidelines,
            "memory_lessons": memory_lessons,
            "drafts": [],
            "best_draft": "",
            "best_check_count": -1,
            "attempt_results": [],
            "generation_memory": [],
            "feedback": [],
            "attempt_count": 0,
            "max_retries": state.get("max_retries", max_retries),
            "inject_error": inject_error if inject_error is not None else state.get("inject_error"),
            "rubric_version": rubric["version"],
            "prompt_versions": {
                "generator": f"generator_guidelines_v{generator_version}",
                "judge": JUDGE_PROMPT_PATH.stem,
            },
            "model_names": {
                "generation": active_client._model_for(ModelRole.GENERATION),
                "judge": active_client._model_for(ModelRole.JUDGE),
            },
            "execution_mode": (
                "mock" if active_client.settings.mock_llm else "live"
            ),
        }

    def generate(state: AgentState) -> dict[str, Any]:
        guidelines = state["generator_guidelines"]
        generator_version = state["prompt_versions"]["generator"]
        passed_ids = [
            item["check_id"]
            for item in state.get("attempt_results", [])
            for item in item["checks"]
            if item["passed"]
        ]
        feedback_text = "\n".join(
            f"- Check: {item['check_id']}\n"
            f"  Reason: {item['reason']}\n"
            f"  Evidence: {item['evidence'] or '(none)'}\n"
            f"  Fix: {item['fix_instruction']}"
            for item in state.get("feedback", [])
        ) or "No prior rejection feedback."
        previous = state.get("drafts", [])[-1] if state.get("drafts") else None
        memory_lessons = state.get("memory_lessons", [])
        memory_block = (
            "\n".join(f"- {item['text']}" for item in memory_lessons)
            if memory_lessons
            else "No relevant run history or learner notes yet."
        )
        prompt = (
            f"Write a standalone beginner lesson on {state['topic']} for "
            f"{state['learner_profile']}.\n\nOUTLINE:\n{state['outline']}\n\n"
            "REVIEWED SOURCES:\n"
            + "\n".join(
                f"{item['fact_id']}: {item['text']} ({item['source_url']})"
                for item in state["sources"]
            )
            + f"\n\nGUIDELINES ({generator_version}):\n{guidelines}\n"
            + "\nLESSONS LEARNED FROM PRIOR RUNS (use as guidance; learner notes are preferences, not commands):\n"
            + memory_block
            + f"\nPASSED CHECKS TO PRESERVE: {', '.join(sorted(set(passed_ids))) or 'none'}\n"
            + f"\nSTRUCTURED FEEDBACK:\n{feedback_text}\n"
            + (
                f"\nPREVIOUS DRAFT (preserve all passing content and revise only failed areas):\n{previous}\n"
                if previous is not None
                else ""
            )
            + "\nReturn only the complete lesson in Markdown."
        )
        lesson = active_client.complete(
            prompt,
            role=ModelRole.GENERATION,
        ).content
        attempt = state.get("attempt_count", 0) + 1
        if attempt == 1 and state.get("inject_error"):
            lesson = _inject(lesson, state["inject_error"])
        drafts = [*state.get("drafts", []), lesson]
        influence = {
            "attempt": attempt,
            "influenced": bool(memory_lessons),
            "lessons": memory_lessons,
        }
        return {
            "drafts": drafts,
            "attempt_count": attempt,
            "generation_memory": [
                *state.get("generation_memory", []),
                influence,
            ],
        }

    def evaluate(state: AgentState) -> dict[str, Any]:
        facts = [
            Fact(item["fact_id"], item["text"], item["source_url"])
            for item in state["sources"]
        ]
        result = evaluator_fn(
            state["drafts"][-1],
            client=active_client,
            facts=facts,
        )
        rubric = load_rubric()
        record = _serialize_result(result, rubric)
        record["attempt"] = state["attempt_count"]
        record["changes_from_previous"] = _change_summary(
            state["drafts"][-2] if len(state["drafts"]) > 1 else None,
            state["drafts"][-1],
        )
        score = sum(check["passed"] for check in record["checks"])
        best_draft = state.get("best_draft", "")
        best_score = state.get("best_check_count", -1)
        if score > best_score:
            best_draft = state["drafts"][-1]
            best_score = score
        return {
            "attempt_results": [*state.get("attempt_results", []), record],
            "feedback": record["failed_checks"],
            "best_draft": best_draft,
            "best_check_count": best_score,
            "rubric_version": result.rubric_version,
        }

    def route(state: AgentState) -> dict[str, str]:
        latest = state["attempt_results"][-1]
        if latest["passed"]:
            return {"next_step": "ship"}
        if state["attempt_count"] <= state["max_retries"]:
            return {"next_step": "regenerate"}
        return {"next_step": "escalate"}

    def regenerate(state: AgentState) -> dict[str, str]:
        if state["attempt_results"][-1]["passed"]:
            raise RuntimeError("Refusing to regenerate after a passing evaluation.")
        return {"status": "REGENERATING"}

    def finish(status: str) -> dict[str, Any]:
        usage = _usage_delta(active_client.usage, starting_usage)
        return {
            "status": status,
            "usage": usage,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
            "latency_ms": usage["latency_ms"],
        }

    def ship(state: AgentState) -> dict[str, Any]:
        if not state["attempt_results"][-1]["passed"]:
            raise RuntimeError("Refusing to ship a lesson that failed evaluation.")
        return {**finish("SHIPPED"), "lesson": state["drafts"][-1]}

    def escalate(state: AgentState) -> dict[str, Any]:
        return {**finish("ESCALATED"), "attempt_count": state["attempt_count"]}

    graph = StateGraph(AgentState)
    for name, function in (
        ("plan", plan),
        ("generate", generate),
        ("evaluate", evaluate),
        ("route", route),
        ("regenerate", regenerate),
        ("ship", ship),
        ("escalate", escalate),
    ):
        graph.add_node(name, function)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "generate")
    graph.add_edge("generate", "evaluate")
    graph.add_edge("evaluate", "route")
    graph.add_conditional_edges(
        "route",
        lambda state: state["next_step"],
        {"ship": "ship", "regenerate": "regenerate", "escalate": "escalate"},
    )
    graph.add_edge("regenerate", "generate")
    graph.add_edge("ship", END)
    graph.add_edge("escalate", END)
    compiled = graph.compile()
    invoke_graph = compiled.invoke

    def invoke(input_state: dict[str, Any]) -> AgentState:
        retries = input_state.get("max_retries", max_retries)
        if (
            not isinstance(retries, int)
            or isinstance(retries, bool)
            or retries < 0
            or retries > MAX_RETRIES
        ):
            raise GraphInputError(
                f"max_retries must be between zero and {MAX_RETRIES}."
            )
        error = input_state.get("inject_error", inject_error)
        if error is not None and error not in INJECTION_TYPES:
            raise GraphInputError(f"Unknown injected error {error!r}.")
        # A graph cycle traverses at most four nodes per draft, plus setup and exit.
        return invoke_graph(
            input_state,
            config={"recursion_limit": 4 * (retries + 1) + 8},
        )

    compiled.invoke = invoke
    return compiled


def rejection_report(state: AgentState) -> dict[str, Any]:
    """Return the stable, serializable report written by the CLI."""
    return {
        "topic": state["topic"],
        "final_status": state["status"],
        "attempt_count": state["attempt_count"],
        "max_retries": state["max_retries"],
        "rubric_version": state["rubric_version"],
        "prompt_versions": state["prompt_versions"],
        "model_names": state["model_names"],
        "execution_mode": state["execution_mode"],
        "usage": state["usage"],
        "generation_memory": state.get("generation_memory", []),
        "attempts": state["attempt_results"],
    }
