#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

# Keep the demonstration offline and prevent accidental real-provider calls.
MOCK_LLM=1
export MOCK_LLM

memory_db="outputs/demo_memory.sqlite3"
output_dir="outputs/demo_runs"

python -m src.cli run \
    --topic "Introduction to RAG" \
    --mock \
    --output-dir "$output_dir" \
    --memory-db "$memory_db"

python -m src.cli run \
    --topic "Introduction to RAG" \
    --inject-error jargon \
    --max-retries 2 \
    --mock \
    --output-dir "$output_dir" \
    --memory-db "$memory_db"

python -m src.cli memory --memory-db "$memory_db"

python -m src.cli evolve \
    --memory-db "$memory_db" \
    --report outputs/demo_evolution_report.md \
    --changelog outputs/demo_CHANGELOG.md
