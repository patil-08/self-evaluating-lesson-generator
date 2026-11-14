from __future__ import annotations

from pathlib import Path

import pytest

from src.checks_code import evaluate_code_checks
from src.rubric import RubricError, load_rubric

GOOD_BEGINNER_LESSON = """# Introduction to RAG

## What is RAG?
RAG means Retrieval-Augmented Generation, a way for a computer to find helpful
text before it writes an answer. It can search notes that a person supplies.
The answer can use details from those notes. This can help when a model does not
know a private rule or a new change.

## How does RAG work?
First, a person asks a question. Next, the system searches its saved notes.
It selects text that matches the question. A long page can be split into small
parts called chunks. A chunk is a small piece of a page that can be searched.
An embedding is a list of numbers that represents some meaning in text.
A vector database is a tool that stores these number patterns for search.
The language model is an AI program that reads and writes words. The system
gives the model the question and the selected text. Then, the model writes an
answer that uses the text it found.

## Everyday worked example
Think about a student who needs the date of a science exam. The student has a
school notice with the date. RAG works in a similar way, but a computer searches
the supplied notes.
First, the student asks, "When is the science exam?"
Next, the helper finds the school notice with the date.
Then, the helper uses that date to answer the question.
Finally, the student can check the notice.
The notice is like the saved information. Finding the right line is retrieval.
Giving that line to the helper adds context. Writing the date is generation.
This example shows the main steps without using a computer term for each one.

## Why does RAG matter?
A model may not know a new school rule or a private guide. RAG can search that
information before the model answers. This can make an answer more useful for
questions about the supplied notes. A system can also show the source text.
Then a person can check where the answer came from.

## Mini glossary
- **RAG**: A way to search information before an AI writes an answer.
- **Retrieval**: Finding useful text for a question.
- **Embedding**: A list of numbers that represents some meaning in text.
- **Vector database**: A tool that stores number patterns for search.
- **Language model**: An AI program that can read and write words.

## Limits
RAG does not guarantee a correct answer. The search may find the wrong text.
The model can still be wrong, so important answers need checking.
"""


def _result(lesson: str, check_id: str):
    results = evaluate_code_checks(lesson)
    return next(result for result in results if result.check_id == check_id)


def test_complete_beginner_lesson_passes_all_deterministic_checks() -> None:
    results = evaluate_code_checks(GOOD_BEGINNER_LESSON)

    assert results
    assert all(result.passed for result in results), [
        (result.check_id, result.reason)
        for result in results
        if not result.passed
    ]


def test_sentence_check_rejects_long_run_on_sentence() -> None:
    lesson = GOOD_BEGINNER_LESSON + "\n" + (
        "This sentence is deliberately very long and includes many extra words "
        "so that it passes thirty words and clearly becomes difficult to read "
        "for someone who is new to this topic and has not learned technical ideas."
    )

    result = _result(lesson, "BEGIN-02")

    assert not result.passed
    assert "longest" in result.reason


def test_readability_check_rejects_dense_technical_prose() -> None:
    dense_sentence = (
        "The computational representation facilitates multidimensional "
        "semantic similarity optimization through probabilistic "
        "transformations."
    )
    lesson = GOOD_BEGINNER_LESSON + "\n" + (dense_sentence + " ") * 20

    result = _result(lesson, "BEGIN-03")

    assert not result.passed
    assert "Flesch Reading Ease" in result.reason


def test_plain_vocabulary_check_rejects_advanced_word() -> None:
    lesson = GOOD_BEGINNER_LESSON.replace(
        "This can make an answer more useful",
        "This can facilitate an answer",
    )

    result = _result(lesson, "BEGIN-04")

    assert not result.passed
    assert "facilitate" in result.reason


def test_style_check_rejects_idiom_and_phrasal_verb_heavy_text() -> None:
    lesson = GOOD_BEGINNER_LESSON.replace(
        "RAG can search that",
        "RAG can hit the ground running and look up that",
    )

    result = _result(lesson, "STYLE-01")

    assert not result.passed
    assert "hit the ground running" in result.reason


def test_jargon_must_be_defined_near_first_use() -> None:
    lesson = GOOD_BEGINNER_LESSON.replace(
        "An embedding is a list of numbers that represents some meaning in text.",
        "An embedding helps the system search.",
    )

    result = _result(lesson, "JARG-01")

    assert not result.passed
    assert "embedding" in result.reason


def test_glossary_must_define_each_required_term() -> None:
    lesson = GOOD_BEGINNER_LESSON.replace(
        "- **Embedding**: A list of numbers that represents some meaning in text.",
        "- **Embedding**:",
    )

    result = _result(lesson, "GLOSS-01")

    assert not result.passed
    assert "embedding" in result.reason


def test_everyday_and_worked_example_require_familiar_ordered_steps() -> None:
    lesson = GOOD_BEGINNER_LESSON.replace(
        "First, the student asks, \"When is the science exam?\"\n"
        "Next, the helper finds the school notice with the date.\n"
        "Then, the helper uses that date to answer the question.\n"
        "Finally, the student can check the notice.",
        "The system searches information and writes an answer.",
    )

    assert not _result(lesson, "EXAMPLE-02").passed


def test_limitation_and_lesson_length_are_mandatory() -> None:
    no_limit = GOOD_BEGINNER_LESSON.replace(
        "RAG does not guarantee a correct answer. The search may find the wrong text.\n"
        "The model can still be wrong, so important answers need checking.",
        "RAG can be useful for many questions.",
    )
    assert not _result(no_limit, "LIMIT-01").passed

    short_lesson = "## What is RAG?\nRAG finds text."
    assert not _result(short_lesson, "LENGTH-01").passed


def test_rubric_checks_are_hard_and_cover_all_six_dimensions() -> None:
    rubric = load_rubric()

    assert rubric.version == "1.0"
    assert all(check.type in {"code", "llm"} for check in rubric.checks)
    assert {check.dimension for check in rubric.checks} == {
        "accurate_and_grounded",
        "beginner_friendly_language",
        "teaches_by_example",
        "no_unexplained_jargon",
        "covers_key_points",
        "coherent_teaching_flow",
    }


def test_rubric_loader_rejects_advisory_checks(tmp_path: Path) -> None:
    rubric_file = tmp_path / "advisory.yaml"
    rubric_file.write_text(
        """version: "test"
checks:
  - id: TEST-01
    dimension: covers_key_points
    type: code
    severity: advisory
    question: "Does this check pass?"
    pass_criteria: "It passes."
    fail_examples: ["It fails."]
""",
        encoding="utf-8",
    )

    with pytest.raises(RubricError, match="advisory checks are forbidden"):
        load_rubric(rubric_file)
