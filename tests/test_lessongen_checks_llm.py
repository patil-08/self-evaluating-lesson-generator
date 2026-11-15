from lessongen.checks_llm import _build_prompt
from lessongen.evaluator import load_rubric
from lessongen.sources import load_facts


def test_live_judge_prompt_does_not_repeat_lesson_and_facts() -> None:
    lesson = "RAG finds useful text before a model writes an answer."
    llm_checks = [
        check for check in load_rubric()["checks"] if check["type"] == "llm"
    ]

    prompt = _build_prompt(
        lesson,
        llm_checks,
        load_facts(),
        include_mock_payload=False,
    )

    assert prompt.count(lesson) == 1
    assert prompt.count('"fact_id"') == len(load_facts())
    assert "Evaluation input:" not in prompt


def test_mock_judge_prompt_keeps_structured_payload() -> None:
    lesson = "RAG finds useful text before a model writes an answer."
    llm_checks = [
        check for check in load_rubric()["checks"] if check["type"] == "llm"
    ]

    prompt = _build_prompt(
        lesson,
        llm_checks,
        load_facts(),
        include_mock_payload=True,
    )

    assert "Evaluation input:" in prompt
