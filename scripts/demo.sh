#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

# Keep the demonstration offline and isolate its state from project data.
MOCK_LLM=1
export MOCK_LLM
demo_root=$(mktemp -d "${TMPDIR:-/tmp}/lessongen-demo.XXXXXX")
export LESSONGEN_MEMORY_DB="$demo_root/memory.sqlite3"
baseline_dir="$demo_root/baseline"
injected_dir="$demo_root/false-claim"
follow_up_dir="$demo_root/follow-up"

python -m lessongen.cli run \
    --topic "Introduction to RAG" \
    --mock \
    --out "$baseline_dir"

run_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["run_id"])' \
    "$baseline_dir/rejection_log.json")

python -m lessongen.cli feedback \
    --run "$run_id" \
    --note "Use a familiar everyday example."

python -m lessongen.cli run \
    --topic "Introduction to RAG" \
    --inject-error false_claim \
    --max-retries 1 \
    --mock \
    --out "$injected_dir"

python -m lessongen.cli run \
    --topic "RAG follow-up" \
    --mock \
    --out "$follow_up_dir"

python -m lessongen.cli memory --limit 5

python -m lessongen.cli evolve \
    --mock \
    --report "$demo_root/evolution_report.md" \
    --decision-log "$demo_root/evolution_decisions.jsonl"

printf '\nDemo artifacts retained at: %s\n' "$demo_root"
