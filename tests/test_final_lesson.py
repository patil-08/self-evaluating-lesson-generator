from pathlib import Path

from src.config import Settings
from src.evaluator import evaluate_lesson
from src.llm import LLMClient


ROOT = Path(__file__).resolve().parents[1]


def test_final_lesson_passes_the_hard_mock_rubric() -> None:
    document = (ROOT / "FINAL_LESSON.md").read_text(encoding="utf-8")
    lesson_start = document.index("# Introduction to RAG")
    lesson_end = document.index("\n---\n", lesson_start)
    lesson = document[lesson_start:lesson_end]
    client = LLMClient(
        settings=Settings(
            mock_llm=True,
            api_key=None,
            base_url="https://api.openai.com/v1",
            gen_model="",
            judge_model="",
        )
    )

    result = evaluate_lesson(lesson, client=client)

    assert result.passed
