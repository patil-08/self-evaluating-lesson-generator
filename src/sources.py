"""Load the small, reviewed, ID-addressable RAG fact collection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_DEFAULT_FACTS_PATH = Path(__file__).resolve().parents[1] / "sources" / "rag_facts.json"
_FACT_ID_PATTERN = re.compile(r"F\d{2}\Z")


class FactSourceError(ValueError):
    """Raised when the source facts file is missing or malformed."""


@dataclass(frozen=True)
class Fact:
    id: str
    fact: str
    source_url: str


def load_facts(path: str | Path | None = None) -> list[Fact]:
    """Load facts with stable IDs, paraphrases, and absolute source URLs."""
    facts_path = Path(path) if path is not None else _DEFAULT_FACTS_PATH
    try:
        raw_facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FactSourceError(f"Fact source file was not found: {facts_path}") from error
    except json.JSONDecodeError as error:
        raise FactSourceError(
            f"Fact source file is not valid JSON: {facts_path} "
            f"(line {error.lineno}, column {error.colno})."
        ) from error
    except OSError as error:
        raise FactSourceError(f"Could not read fact source file {facts_path}: {error}") from error

    if not isinstance(raw_facts, list):
        raise FactSourceError("Fact source file must contain a JSON list.")

    facts: list[Fact] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_facts):
        location = f"Fact entry {index + 1}"
        if not isinstance(item, dict):
            raise FactSourceError(f"{location} must be a JSON object.")

        fact_id = item.get("id")
        text = item.get("fact")
        source_url = item.get("source_url")
        if not isinstance(fact_id, str) or not _FACT_ID_PATTERN.fullmatch(fact_id):
            raise FactSourceError(f"{location} must have an ID like F01.")
        if fact_id in seen_ids:
            raise FactSourceError(f"Duplicate fact ID: {fact_id}.")
        if not isinstance(text, str) or not text.strip():
            raise FactSourceError(f"{fact_id} must have a non-empty fact.")
        if not isinstance(source_url, str) or not source_url.strip():
            raise FactSourceError(f"{fact_id} must have a source_url.")
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise FactSourceError(f"{fact_id} source_url must be an absolute HTTP(S) URL.")

        seen_ids.add(fact_id)
        facts.append(Fact(id=fact_id, fact=text.strip(), source_url=source_url.strip()))

    if not facts:
        raise FactSourceError("Fact source file must contain at least one fact.")
    return facts


def get_fact(fact_id: str, facts: list[Fact] | None = None) -> Fact:
    """Return one fact by ID, raising KeyError rather than hiding a bad lookup."""
    for fact in facts if facts is not None else load_facts():
        if fact.id == fact_id:
            return fact
    raise KeyError(f"No RAG source fact has ID {fact_id!r}.")
