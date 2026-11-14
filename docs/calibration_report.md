# Evaluator Calibration Report

- Generated: 2026-11-14T15:36:21+00:00
- Rubric version: `1.0`
- Fixture set: 12 lessons (4 known-good, 8 deliberately flawed).
- Decision: every hard check is required; any missed expected failure or rejected good lesson is a calibration failure.

## Mock run

- Known-good lessons passing: **4/4**.
- Expected flaw checks caught: **17/17**.
- Exact per-check outcomes: **204/204**.
- Calibration result: **PASS**.

Each matrix cell shows `P` (pass) or `F` (fail). A check succeeds when that result matches the fixture's expectation; `!` marks a mismatch and `E` marks an evaluator error.

| Fixture | Expected | Overall | ACC-01 | COVER-01 | BEGIN-01 | BEGIN-02 | BEGIN-03 | BEGIN-04 | STYLE-01 | JARG-01 | JARG-02 | GLOSS-01 | EXAMPLE-01 | EXAMPLE-02 | EXAMPLE-03 | COVER-02 | LIMIT-01 | FLOW-01 | LENGTH-01 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `good-school-notice` | PASS | PASS | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `good-library-card` | PASS | PASS | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `good-cricket-score` | PASS | PASS | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `good-shop-policy` | PASS | PASS | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `flaw-false-claim` | FAIL: ACC-01 | FAIL | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `flaw-unexplained-jargon` | FAIL: ACC-01, JARG-02 | FAIL | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `flaw-no-example` | FAIL: EXAMPLE-01, EXAMPLE-02, EXAMPLE-03, FLOW-01 | FAIL | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | F✓ | F✓ | F✓ | P✓ | P✓ | F✓ | P✓ |
| `flaw-wrong-order` | FAIL: COVER-01, FLOW-01 | FAIL | P✓ | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | F✓ | P✓ |
| `flaw-long-sentences` | FAIL: BEGIN-01, BEGIN-02 | FAIL | P✓ | P✓ | F✓ | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `flaw-missing-section` | FAIL: COVER-01, COVER-02, FLOW-01 | FAIL | P✓ | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | F✓ | P✓ | F✓ | P✓ |
| `flaw-idioms` | FAIL: BEGIN-01, STYLE-01 | FAIL | P✓ | P✓ | F✓ | P✓ | P✓ | P✓ | F✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ |
| `flaw-missing-limitation` | FAIL: LIMIT-01 | FAIL | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | P✓ | F✓ | P✓ | P✓ |

No per-check mismatches were recorded in this run.

## Real-provider run

- Not run: no LLM_API_KEY is configured.

## Calibration caveats

Mock mode is deterministic and is intended for offline regression checks. Its judge uses explicit heuristics for the deliberate false-guarantee, unknown-jargon, missing-section/example, ordering, long-sentence, and idiom cases. For clean lessons, it verifies one representative grounded claim rather than performing full semantic claim extraction. Only a configured real judge can exercise the full prompt-based claim audit; its reported results remain model judgments, not proof of factual truth.

The known-good lessons are curated against the local RAG facts. The deliberately flawed cases are generated from those lessons using the mutations recorded in `tests/fixtures/manifest.json`.
