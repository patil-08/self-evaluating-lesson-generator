"""Repeatable checks for measurable lesson requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from lessongen.config import (
    MAX_JARGON_DEFINITION_WORDS,
    MAX_LESSON_WORDS,
    MAX_PHRASAL_VERBS_PER_100_WORDS,
    MAX_SENTENCE_WORDS,
    MAX_SENTENCE_WORDS_HARD,
    MIN_ADVANCED_WORD_HITS,
    MIN_EXAMPLE_WORDS,
    MIN_GLOSSARY_TERMS,
    MIN_LESSON_WORDS,
    MIN_READABILITY_SCORE,
    MIN_REQUIRED_SECTIONS,
    MIN_SHORT_SENTENCE_RATIO,
    MIN_WORKED_EXAMPLE_STEPS,
)

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
DEFINITION_CUES = re.compile(
    r"\b(?:means|refers to|is called|is short for|is a|is an|is the process|"
    r"is a way|is a list|is a tool|are small|called|stores|searches)\b",
    re.IGNORECASE,
)

SECTION_ALIASES = {
    "what": ("what is rag", "what rag is", "what does rag mean"),
    "why": ("why does rag matter", "why rag matters", "why it matters"),
    "how": ("how does rag work", "how rag works", "how it works"),
    "example": ("example", "worked example"),
    "limitations": ("limitations", "limits", "what rag cannot do"),
    "glossary": ("glossary", "key words", "key terms"),
}
ADVANCED_WORDS = (
    "aforementioned", "commence", "consequently", "facilitate", "henceforth",
    "implementation", "leverage", "methodology", "optimization",
    "approximately", "utilize", "subsequently", "functionality",
)


@dataclass(frozen=True)
class CodeCheckResult:
    check_id: str
    passed: bool
    reason: str
    evidence_quote: str


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _clean(text: str, *, remove_headings: bool = False) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    if remove_headings:
        cleaned = HEADING_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(HEADING_RE.finditer(text))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = re.sub(r"[*_`]", "", match.group(1)).strip().lower()
        sections.append((title, text[match.end():end].strip()))
    return sections


def _section(text: str, alias_group: str) -> str | None:
    aliases = SECTION_ALIASES[alias_group]
    return next(
        (
            body
            for title, body in _sections(text)
            if any(alias in title for alias in aliases)
        ),
        None,
    )


def _readability(text: str) -> float | None:
    sentences = [
        item for item in SENTENCE_RE.split(_clean(text, remove_headings=True)) if item
    ]
    words = [word.lower() for sentence in sentences for word in _words(sentence)]
    if not sentences or not words:
        return None

    def syllables(word: str) -> int:
        word = re.sub(r"[^a-z]", "", word)
        groups = len(re.findall(r"[aeiouy]+", word))
        if word.endswith("e") and not word.endswith(("le", "ye")) and groups > 1:
            groups -= 1
        return max(1, groups)

    total_syllables = sum(syllables(word) for word in words)
    return 206.835 - 1.015 * len(words) / len(sentences) - 84.6 * total_syllables / len(words)


def _check_sections(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    headings = [title for title, _ in _sections(lesson)]
    parameters = check.get("parameters", {})
    order = parameters.get(
        "section_order",
        parameters.get("required_order", ["what", "why", "how"]),
    )
    positions = []
    for section_name in order:
        aliases = SECTION_ALIASES.get(section_name)
        if aliases is None:
            raise ValueError(f"Unknown section alias in rubric: {section_name!r}")
        position = next(
            (index for index, title in enumerate(headings) if any(alias in title for alias in aliases)),
            None,
        )
        if position is None:
            return False, f"Missing required {section_name!r} section.", ""
        positions.append(position)
    valid = len(positions) >= MIN_REQUIRED_SECTIONS and positions == sorted(positions)
    return valid, (
        "Required sections are present in order."
        if valid else "Required sections are not in the required order."
    ), " | ".join(headings[index] for index in positions)


def _check_sentence_length(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    parameters = check.get("parameters", {})
    max_sentence_words = int(parameters.get("max_sentence_words", MAX_SENTENCE_WORDS))
    minimum_ratio = float(
        parameters.get("minimum_ratio_at_or_below_max", MIN_SHORT_SENTENCE_RATIO)
    )
    absolute_max = int(
        parameters.get("absolute_max_sentence_words", MAX_SENTENCE_WORDS_HARD)
    )
    sentences = [
        sentence.strip()
        for sentence in SENTENCE_RE.split(_clean(lesson, remove_headings=True))
        if sentence.strip()
    ]
    if not sentences:
        return False, "No lesson sentences were found.", ""
    lengths = [len(_words(sentence)) for sentence in sentences]
    ratio = sum(length <= max_sentence_words for length in lengths) / len(lengths)
    longest = max(lengths)
    passed = ratio >= minimum_ratio and longest <= absolute_max
    evidence = next(
        (
            sentence
            for sentence, count in zip(sentences, lengths)
            if count > max_sentence_words
        ),
        "",
    )
    return passed, (
        f"{ratio:.0%} of sentences are at most {max_sentence_words} words; "
        f"the longest has {longest} (hard limit {absolute_max})."
    ), evidence


def _check_readability(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    score = _readability(lesson)
    minimum_score = float(
        check.get("parameters", {}).get(
            "minimum_flesch_reading_ease",
            MIN_READABILITY_SCORE,
        )
    )
    passed = score is not None and score >= minimum_score
    return passed, (
        f"Approximate Flesch Reading Ease is {score:.1f}; minimum is "
        f"{minimum_score:.1f}." if score is not None
        else "Readability score could not be calculated."
    ), ""


def _check_plain_words(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    parameters = check.get("parameters", {})
    forbidden = parameters.get("forbidden_words", ADVANCED_WORDS)
    maximum_hits = int(parameters.get("maximum_hits", MIN_ADVANCED_WORD_HITS))
    hits = [
        word for word in forbidden
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lesson, re.IGNORECASE)
    ]
    passed = len(hits) <= maximum_hits
    return passed, f"Configured difficult-word hits: {', '.join(hits) or 'none'}.", ", ".join(hits)


def _check_style(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    params = check.get("parameters", {})
    idioms = params.get("idioms", [])
    idiom_hits = [
        phrase for phrase in idioms
        if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lesson, re.IGNORECASE)
    ]
    phrasals = params.get("phrasal_verbs", [])
    count = sum(
        len(re.findall(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lesson, re.IGNORECASE))
        for phrase in phrasals
    )
    word_count = max(1, len(_words(_clean(lesson))))
    rate = count * 100 / word_count
    maximum = float(params.get("maximum_per_100_words", MAX_PHRASAL_VERBS_PER_100_WORDS))
    return not idiom_hits and rate <= maximum, (
        f"Idiom hits: {', '.join(idiom_hits) or 'none'}; phrasal verbs: "
        f"{count} ({rate:.2f} per 100 words, limit {maximum:.2f})."
    ), ", ".join(idiom_hits)


def _has_definition(after: str, window: int) -> bool:
    sentence = SENTENCE_RE.split(after, maxsplit=1)[0]
    return bool(DEFINITION_CUES.search(" ".join(_words(sentence)[:window])))


def _check_jargon(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    params = check.get("parameters", {})
    terms = sorted(params.get("known_terms", []), key=len, reverse=True)
    window = int(params.get("definition_window_words", MAX_JARGON_DEFINITION_WORDS))
    prose = _clean(lesson, remove_headings=True)
    missing = []
    for term in terms:
        match = re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", prose, re.IGNORECASE)
        if match and not _has_definition(prose[match.end():], window):
            preceding = " ".join(_words(prose[:match.start()])[-window:])
            if not re.search(r"\b(?:called|known as|means)\s*$", preceding, re.IGNORECASE):
                missing.append(term)
    return not missing, (
        f"Terms without a nearby first-use definition: {', '.join(missing) or 'none'}."
    ), ", ".join(missing)


def _check_glossary(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    body = _section(lesson, "glossary") or ""
    entries = re.findall(
        r"(?m)^\s*[-*]\s+(?:\*\*)?([^*:]+?)(?:\*\*)?\s*:\s*(.+)$",
        body,
    )
    parameters = check.get("parameters", {})
    required = parameters.get("required_terms", [])
    minimum_entries = int(parameters.get("minimum_entries", MIN_GLOSSARY_TERMS))
    missing = [
        term for term in required
        if not any(term.casefold() in entry[0].casefold() and len(_words(entry[1])) >= 3 for entry in entries)
    ]
    passed = len(entries) >= minimum_entries and not missing
    return passed, (
        f"Glossary has {len(entries)} entries; missing definitions: "
        f"{', '.join(missing) or 'none'}."
    ), ", ".join(missing)


def _check_example(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    example = _section(lesson, "example")
    if example is None:
        return False, "No everyday example section was found.", ""
    parameters = check.get("parameters", {})
    familiar = [
        item for item in parameters.get("familiar_words", [])
        if re.search(r"(?<!\w)" + re.escape(item) + r"(?!\w)", example, re.IGNORECASE)
    ]
    word_count = len(_words(_clean(example)))
    minimum_words = int(parameters.get("minimum_example_words", MIN_EXAMPLE_WORDS))
    passed = bool(familiar) and word_count >= minimum_words
    return passed, f"Example has {word_count} words and familiar anchors: {', '.join(familiar) or 'none'}.", example[:220]


def _check_example_steps(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    example = _section(lesson, "example") or ""
    numbered = re.findall(r"(?m)^\s*(?:[-*]\s*)?\d+[.)]\s+", example)
    parameters = check.get("parameters", {})
    markers = parameters.get("sequence_markers", [])
    marker_count = sum(
        len(re.findall(r"(?<!\w)" + re.escape(marker) + r"(?!\w)", example, re.IGNORECASE))
        for marker in markers
    )
    steps = max(len(numbered), marker_count)
    minimum_steps = int(parameters.get("minimum_steps", MIN_WORKED_EXAMPLE_STEPS))
    return steps >= minimum_steps, (
        f"Found {steps} ordered example steps; at least {minimum_steps} are required."
    ), example[:220]


def _check_limits(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    body = _section(lesson, "limitations")
    if body is None:
        return False, "No limitations section was found.", ""
    phrases = check.get("parameters", {}).get("limitation_phrases", [])
    present = [phrase for phrase in phrases if phrase.casefold() in body.casefold()]
    return bool(present), f"Limitation wording found: {', '.join(present) or 'none'}.", body[:220]


def _check_length(lesson: str, check: dict[str, Any]) -> tuple[bool, str, str]:
    count = len(_words(_clean(lesson)))
    parameters = check.get("parameters", {})
    minimum_words = int(parameters.get("minimum_words", MIN_LESSON_WORDS))
    maximum_words = int(parameters.get("maximum_words", MAX_LESSON_WORDS))
    passed = minimum_words <= count <= maximum_words
    return passed, (
        f"Lesson contains {count} words; allowed range is "
        f"{minimum_words}-{maximum_words}."
    ), ""


CHECKS = {
    "COVER-01": _check_sections,
    "BEGIN-02": _check_sentence_length,
    "BEGIN-03": _check_readability,
    "BEGIN-04": _check_plain_words,
    "STYLE-01": _check_style,
    "JARG-01": _check_jargon,
    "GLOSS-01": _check_glossary,
    "EXAMPLE-01": _check_example,
    "EXAMPLE-02": _check_example_steps,
    "LIMIT-01": _check_limits,
    "LENGTH-01": _check_length,
}


def evaluate_code_checks(
    lesson: str,
    rubric_checks: list[dict[str, Any]],
) -> list[CodeCheckResult]:
    results = []
    for check in rubric_checks:
        if check["type"] != "code":
            continue
        function = CHECKS.get(check["id"])
        if function is None:
            raise ValueError(f"No deterministic implementation for {check['id']}.")
        passed, reason, evidence = function(lesson, check)
        results.append(CodeCheckResult(check["id"], passed, reason, evidence))
    return results
