"""Load atomic, cited RAG facts from the project source file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_PATH = ROOT / "sources" / "rag_facts.md"
FACT_PATTERN = re.compile(
    r"(?m)^- \*\*(F\d{2})\*\*:\s*(.*?)\s+Source:\s*(https?://\S+)\s*$"
)


class SourceError(ValueError):
    """Raised when the reviewed fact file is missing or malformed."""


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    source_url: str


def load_facts(path: str | Path | None = None) -> list[Fact]:
    source_path = Path(path) if path is not None else DEFAULT_SOURCE_PATH
    try:
        content = source_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourceError(f"Cannot read fact source file {source_path}: {error}") from error

    facts: list[Fact] = []
    seen: set[str] = set()
    for match in FACT_PATTERN.finditer(content):
        fact_id, text, source_url = match.groups()
        if fact_id in seen:
            raise SourceError(f"Duplicate fact ID {fact_id}.")
        parsed = urlparse(source_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise SourceError(f"{fact_id} must have an absolute HTTP(S) source URL.")
        if not text.strip():
            raise SourceError(f"{fact_id} has no fact text.")
        facts.append(Fact(fact_id, text.strip(), source_url))
        seen.add(fact_id)

    if not facts:
        raise SourceError(f"No atomic facts were found in {source_path}.")
    return facts


def facts_by_id(facts: list[Fact] | None = None) -> dict[str, Fact]:
    loaded = facts if facts is not None else load_facts()
    return {fact.id: fact for fact in loaded}
