import json
from pathlib import Path

import pytest

from src.sources import FactSourceError, get_fact, load_facts


def test_loads_curated_facts_with_unique_ids_and_citations() -> None:
    facts = load_facts()
    fact_ids = [fact.id for fact in facts]

    assert len(facts) >= 15
    assert len(fact_ids) == len(set(fact_ids))
    assert all(fact.source_url.startswith("https://") for fact in facts)
    assert get_fact("F01", facts).fact.startswith("Retrieval-Augmented Generation")


def test_get_fact_reports_unknown_ids() -> None:
    with pytest.raises(KeyError, match="No RAG source fact has ID"):
        get_fact("F99", [])


def test_load_facts_rejects_duplicate_ids(tmp_path: Path) -> None:
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(
        json.dumps(
            [
                {"id": "F01", "fact": "One.", "source_url": "https://example.com/1"},
                {"id": "F01", "fact": "Two.", "source_url": "https://example.com/2"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(FactSourceError, match="Duplicate fact ID: F01"):
        load_facts(facts_file)


def test_load_facts_rejects_invalid_source_url(tmp_path: Path) -> None:
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(
        json.dumps(
            [{"id": "F01", "fact": "A fact.", "source_url": "not-a-url"}]
        ),
        encoding="utf-8",
    )

    with pytest.raises(FactSourceError, match="absolute HTTP"):
        load_facts(facts_file)
