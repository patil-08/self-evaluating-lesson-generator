from __future__ import annotations

from pathlib import Path

import pytest

from lessongen.sources import SourceError, facts_by_id, load_facts


ROOT = Path(__file__).resolve().parents[1]


def test_loads_stable_fact_ids_and_citations() -> None:
    facts = load_facts(ROOT / "sources" / "rag_facts.md")
    indexed = facts_by_id(facts)

    assert len(facts) >= 15
    assert indexed["F01"].source_url == "https://arxiv.org/abs/2005.11401"
    assert all(fact.text and fact.source_url.startswith("https://") for fact in facts)


def test_rejects_source_without_atomic_facts(tmp_path: Path) -> None:
    source = tmp_path / "empty.md"
    source.write_text("# No facts\n", encoding="utf-8")

    with pytest.raises(SourceError, match="No atomic facts"):
        load_facts(source)


def test_rejects_duplicate_fact_ids(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.md"
    source.write_text(
        "- **F01**: One fact. Source: https://example.com/a\n"
        "- **F01**: A second fact. Source: https://example.com/b\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceError, match="Duplicate fact ID F01"):
        load_facts(source)
