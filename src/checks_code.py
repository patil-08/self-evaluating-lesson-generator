"""Deterministic, binary checks for observable lesson requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from src.config import (
    MAX_SENTENCE_WORDS,
    MAX_SENTENCE_WORDS_HARD,
    MAX_PHRASAL_VERBS_PER_100_WORDS,
    MAX_JARGON_DEFINITION_WORDS,
    MAX_ADVANCED_VOCABULARY_HITS,
    MAX_LESSON_WORDS,
    MIN_EXAMPLE_WORDS,
    MIN_EXAMPLES,
    MIN_GLOSSARY_TERMS,
    MIN_LESSON_WORDS,
    MIN_READABILITY_SCORE,
    MIN_REQUIRED_SECTIONS,
    MIN_SHORT_SENTENCE_RATIO,
    MIN_WORKED_EXAMPLE_STEPS,
)
from src.rubric import Rubric, RubricCheck, load_rubric

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_SECTION_ALIASES = {
    "what": ("what is rag", "what rag is", "what does rag mean", "what rag means"),
    "how": ("how does rag work", "how rag works", "how does it work", "how it works"),
    "why": ("why does rag matter", "why rag matters", "why use rag", "why it matters"),
}
_DEFINITION_CUES = (
    re.compile(r"\b(?:means|refers to|is called|is short for)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:is|are)\s+(?:a|an|the|when|where|used|made|finding|searching|storing)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:a|an)\s+(?:way|tool|system|method|process|program|list|number|type)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:a|an)\s+(?:AI|computer)\s+(?:program|system|tool)\b", re.IGNORECASE),
    re.compile(r"\b(?:stores?|searches?)\b", re.IGNORECASE),
)
_ADVANCED_WORD_FALLBACK = (
    "aforementioned",
    "commence",
    "consequently",
    "facilitate",
    "henceforth",
    "implementation",
    "leverage",
    "methodology",
    "optimization",
    "approximately",
    "utilize",
    "subsequently",
    "functionality",
)


@dataclass(frozen=True)
class CodeCheckResult:
    check_id: str
    dimension: str
    passed: bool
    reason: str
    evidence_quote: str


class CodeCheckError(ValueError):
    """Raised when a rubric requests a deterministic check not implemented here."""


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _clean_markdown(text: str, *, remove_headings: bool = False) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    if remove_headings:
        cleaned = _HEADING_RE.sub(" ", cleaned)
    cleaned = _LINK_RE.sub(r"\1", cleaned)
    cleaned = _URL_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _sections(text: str) -> list[tuple[str, str, int]]:
    matches = list(_HEADING_RE.finditer(text))
    sections: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = re.sub(r"[*_`]", "", match.group(1)).strip().lower()
        body = text[body_start:body_end].strip()
        sections.append((title, body, match.start()))
    return sections


def _normalized_heading(heading: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", heading.lower()).strip()


def _first_section(text: str, aliases: tuple[str, ...]) -> tuple[str, int] | None:
    for heading, body, position in _sections(text):
        normalized = _normalized_heading(heading)
        if any(alias in normalized for alias in aliases):
            return body, position
    return None


def _word_count(text: str) -> int:
    return len(_words(_clean_markdown(text)))


def _sentences(text: str) -> list[str]:
    prose = _clean_markdown(text, remove_headings=True)
    return [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(prose) if sentence.strip()]


def _syllable_count(word: str) -> int:
    normalized = re.sub(r"[^a-z]", "", word.lower())
    if not normalized:
        return 0
    groups = re.findall(r"[aeiouy]+", normalized)
    count = len(groups)
    if normalized.endswith("e") and not normalized.endswith(("le", "ye")) and count > 1:
        count -= 1
    return max(1, count)


def _flesch_reading_ease(text: str) -> float | None:
    sentences = _sentences(text)
    words = [word.lower() for sentence in sentences for word in _words(sentence)]
    if not sentences or not words:
        return None
    syllables = sum(_syllable_count(word) for word in words)
    return 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))


def _phrase_count(text: str, phrases: tuple[str, ...] | list[str]) -> int:
    lowered = text.lower()
    return sum(
        len(re.findall(r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)", lowered))
        for phrase in phrases
    )


def _has_definition(after_term: str, window_words: int) -> bool:
    if re.match(r"\s*[:\u2013-]", after_term):
        return bool(_words(after_term)[:window_words])
    first_sentence = re.split(r"[.!?]\s+", after_term, maxsplit=1)[0]
    words = _words(first_sentence)
    window = " ".join(words[:window_words])
    return any(cue.search(window) for cue in _DEFINITION_CUES)


def _defined_immediately_before(before_term: str, window_words: int) -> bool:
    same_sentence = re.split(r"[.!?]\s+", before_term)[-1]
    preceding_words = _words(same_sentence)[-window_words:]
    return bool(
        re.search(r"\b(?:called|known as|named)\s*$", " ".join(preceding_words), re.IGNORECASE)
    )


def _glossary_entries(text: str) -> list[tuple[str, str]]:
    section = _first_section(text, ("glossary", "key words", "key terms"))
    if section is None:
        return []
    body, _ = section
    entries: list[tuple[str, str]] = []
    entry_pattern = re.compile(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?(.+?)(?:\*\*)?\s*[:\u2013-]\s*(.+?)\s*$"
    )
    for line in body.splitlines():
        match = entry_pattern.match(line)
        if match:
            term = re.sub(r"[*_`]", "", match.group(1)).strip()
            definition = re.sub(r"[*_`]", "", match.group(2)).strip()
            entries.append((term, definition))
    return entries


def _glossary_term_defined(entries: list[tuple[str, str]], required: str) -> bool:
    for term, definition in entries:
        if re.search(r"(?<!\w)" + re.escape(required) + r"(?!\w)", term, re.IGNORECASE):
            if len(_words(definition)) >= 3:
                return True
    return False


def _check_sections(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    sections = _sections(lesson)
    headings = [_normalized_heading(item[0]) for item in sections]
    required_order = check.parameters.get("section_order", list(_SECTION_ALIASES))
    positions: list[int] = []
    for key in required_order:
        aliases = _SECTION_ALIASES.get(key)
        if aliases is None:
            raise CodeCheckError(f"Unknown required section alias in rubric: {key!r}.")
        position = next(
            (index for index, heading in enumerate(headings) if any(alias in heading for alias in aliases)),
            None,
        )
        if position is None:
            return False, f"Missing required '{key}' section.", ""
        positions.append(position)
    if len(positions) < MIN_REQUIRED_SECTIONS or positions != sorted(positions):
        return False, "Required what/how/why sections are not in the required order.", ""
    quoted = " | ".join(sections[position][0] for position in positions)
    return True, "The what, how, and why sections appear in order.", quoted


def _check_sentence_lengths(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    sentences = _sentences(lesson)
    if not sentences:
        return False, "No readable sentences were found.", ""
    target_words = int(check.parameters.get("max_sentence_words", MAX_SENTENCE_WORDS))
    minimum_ratio = float(
        check.parameters.get("minimum_ratio_at_or_below_max", MIN_SHORT_SENTENCE_RATIO)
    )
    absolute_max = int(
        check.parameters.get("absolute_max_sentence_words", MAX_SENTENCE_WORDS_HARD)
    )
    lengths = [len(_words(sentence)) for sentence in sentences]
    ratio = sum(length <= target_words for length in lengths) / len(lengths)
    longest = max(lengths)
    passed = ratio >= minimum_ratio and longest <= absolute_max
    reason = (
        f"{ratio:.0%} of sentences are at most {target_words} words; "
        f"the longest has {longest} words (limit {absolute_max})."
    )
    evidence = next(
        (sentence for sentence, length in zip(sentences, lengths) if length > target_words),
        sentences[0],
    )
    return passed, reason, evidence


def _check_readability(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    score = _flesch_reading_ease(lesson)
    threshold = float(check.parameters.get("minimum_flesch_reading_ease", MIN_READABILITY_SCORE))
    if score is None:
        return False, "A readability score could not be calculated from the lesson.", ""
    return (
        score >= threshold,
        f"Approximate Flesch Reading Ease is {score:.1f}; minimum is {threshold:.1f}.",
        "",
    )


def _check_plain_vocabulary(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    forbidden = tuple(check.parameters.get("forbidden_words", _ADVANCED_WORD_FALLBACK))
    hits = [
        word
        for word in forbidden
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lesson, re.IGNORECASE)
    ]
    max_hits = int(
        check.parameters.get("maximum_hits", MAX_ADVANCED_VOCABULARY_HITS)
    )
    return (
        len(hits) <= max_hits,
        f"Found {len(hits)} configured advanced-word hit(s): {', '.join(hits) or 'none'}.",
        ", ".join(hits),
    )


def _check_idioms(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    idioms = tuple(check.parameters.get("idioms", ()))
    phrasal_verbs = tuple(check.parameters.get("phrasal_verbs", ()))
    idiom_hits = [
        phrase
        for phrase in idioms
        if re.search(r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)", lesson.lower())
    ]
    phrasal_count = _phrase_count(lesson, phrasal_verbs)
    words = max(1, _word_count(lesson))
    per_100 = phrasal_count * 100 / words
    maximum = float(
        check.parameters.get(
            "maximum_per_100_words", MAX_PHRASAL_VERBS_PER_100_WORDS
        )
    )
    passed = not idiom_hits and per_100 <= maximum
    reason = (
        f"Idiom hits: {', '.join(idiom_hits) or 'none'}; listed phrasal verbs: "
        f"{phrasal_count} ({per_100:.2f} per 100 words, limit {maximum:.2f})."
    )
    return passed, reason, ", ".join(idiom_hits) or ""


def _check_jargon_definitions(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    prose = _clean_markdown(lesson, remove_headings=True)
    terms = sorted(check.parameters.get("known_terms", ()), key=len, reverse=True)
    window = int(
        check.parameters.get("definition_window_words", MAX_JARGON_DEFINITION_WORDS)
    )
    missing: list[str] = []
    for term in terms:
        match = re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", prose, re.IGNORECASE)
        if match and not (
            _has_definition(prose[match.end() :], window)
            or _defined_immediately_before(prose[: match.start()], window)
        ):
            missing.append(term)
    return (
        not missing,
        f"Terms without a nearby first-use definition: {', '.join(missing) or 'none'}.",
        ", ".join(missing),
    )


def _check_glossary(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    entries = _glossary_entries(lesson)
    required = tuple(check.parameters.get("required_terms", ()))
    missing = [term for term in required if not _glossary_term_defined(entries, term)]
    minimum = int(check.parameters.get("minimum_entries", MIN_GLOSSARY_TERMS))
    passed = not missing and len(entries) >= minimum
    return (
        passed,
        f"Glossary has {len(entries)} entries; missing required definitions: "
        f"{', '.join(missing) or 'none'}.",
        ", ".join(missing),
    )


def _example_section(lesson: str) -> str | None:
    result = _first_section(
        lesson,
        ("example", "worked example", "everyday example", "a simple example"),
    )
    return result[0] if result is not None else None


def _check_everyday_example(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    example = _example_section(lesson)
    if example is None:
        return False, "No example section heading was found.", ""
    minimum_words = int(
        check.parameters.get("minimum_example_words", MIN_EXAMPLE_WORDS)
    )
    familiar_words = tuple(check.parameters.get("familiar_words", ()))
    present = [
        word for word in familiar_words
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", example, re.IGNORECASE)
    ]
    count = _word_count(example)
    minimum_examples = int(check.parameters.get("minimum_examples", MIN_EXAMPLES))
    passed = len(set(present)) >= minimum_examples and count >= minimum_words
    return (
        passed,
        f"Example section has {count} words and familiar anchors: {', '.join(present) or 'none'}.",
        example[:220],
    )


def _check_worked_example(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    example = _example_section(lesson)
    if example is None:
        return False, "No example section heading was found.", ""
    numbered_steps = re.findall(r"(?m)^\s*(?:[-*]\s*)?\d+[.)]\s+", example)
    markers = tuple(check.parameters.get("sequence_markers", ()))
    marker_count = _phrase_count(example, markers)
    minimum_steps = int(
        check.parameters.get("minimum_steps", MIN_WORKED_EXAMPLE_STEPS)
    )
    steps = max(len(numbered_steps), marker_count)
    return (
        steps >= minimum_steps,
        f"Found {steps} ordered example steps; at least {minimum_steps} are required.",
        example[:220],
    )


def _check_limitation(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    aliases = tuple(check.parameters.get("section_aliases", ()))
    limitation = _first_section(lesson, aliases)
    if limitation is None:
        return False, "No limitations section heading was found.", ""
    body, _ = limitation
    phrases = tuple(check.parameters.get("limitation_phrases", ()))
    present = [phrase for phrase in phrases if phrase.lower() in body.lower()]
    return (
        bool(present),
        f"Limitation wording found: {', '.join(present) or 'none'}.",
        body[:220],
    )


def _check_length(lesson: str, check: RubricCheck) -> tuple[bool, str, str]:
    count = _word_count(lesson)
    minimum = int(check.parameters.get("minimum_words", MIN_LESSON_WORDS))
    maximum = int(check.parameters.get("maximum_words", MAX_LESSON_WORDS))
    return (
        minimum <= count <= maximum,
        f"Lesson contains {count} words; required range is {minimum}–{maximum}.",
        "",
    )


_CODE_CHECKS: dict[
    str, Callable[[str, RubricCheck], tuple[bool, str, str]]
] = {
    "COVER-01": _check_sections,
    "BEGIN-02": _check_sentence_lengths,
    "BEGIN-03": _check_readability,
    "BEGIN-04": _check_plain_vocabulary,
    "STYLE-01": _check_idioms,
    "JARG-01": _check_jargon_definitions,
    "GLOSS-01": _check_glossary,
    "EXAMPLE-01": _check_everyday_example,
    "EXAMPLE-02": _check_worked_example,
    "LIMIT-01": _check_limitation,
    "LENGTH-01": _check_length,
}


def evaluate_code_checks(
    lesson: str,
    rubric: Rubric | None = None,
) -> list[CodeCheckResult]:
    """Run every code-type hard check from a rubric; unknown checks fail loudly."""
    active_rubric = rubric or load_rubric()
    results: list[CodeCheckResult] = []
    for check in active_rubric.checks:
        if check.type != "code":
            continue
        function = _CODE_CHECKS.get(check.id)
        if function is None:
            raise CodeCheckError(
                f"No deterministic implementation exists for rubric check {check.id!r}."
            )
        passed, reason, evidence = function(lesson, check)
        results.append(
            CodeCheckResult(
                check_id=check.id,
                dimension=check.dimension,
                passed=bool(passed),
                reason=reason,
                evidence_quote=evidence,
            )
        )
    return results
