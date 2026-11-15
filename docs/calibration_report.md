# Calibration Report

- **Run mode:** mock (deterministic)
- **Rubric version:** 1.0
- **Fixtures:** 12 (4 good, 8 flawed)
- **Targeted flaw checks caught:** 8/8
- **Good lessons passed:** 4/4

## Overall lesson-level metrics

A lesson is predicted flawed when any hard check rejects it. A planted flaw
is a positive case; a known-good lesson is a negative case.

| Metric | Count | Rate |
| --- | ---: | ---: |
| True positives | 8 | 100.0% recall |
| False positives | 0 | 0.0% of good lessons rejected |
| False negatives | 0 | 0.0% of flawed lessons shipped |
| True negatives | 4 | 100.0% specificity |
| Precision | - | 100.0% |
| Recall | - | 100.0% |

## Fixture-by-fixture results

| Fixture | Planted flaw | Expected failed checks | Actual failed checks | Result |
| --- | --- | --- | --- | --- |
| good_01 | known-good lesson | none | none | PASS |
| good_02 | known-good lesson | none | none | PASS |
| good_03 | known-good lesson | none | none | PASS |
| good_04 | known-good lesson | none | none | PASS |
| false_claim | deliberately flawed lesson | ACC-01 | ACC-01 | PASS |
| unexplained_jargon | deliberately flawed lesson | JARG-02 | JARG-02 | PASS |
| no_example | deliberately flawed lesson | EXAMPLE-01, EXAMPLE-02, EXAMPLE-03, FLOW-01 | EXAMPLE-01, EXAMPLE-02, EXAMPLE-03, FLOW-01 | PASS |
| wrong_order | deliberately flawed lesson | COVER-01, FLOW-01, JARG-01 | COVER-01, FLOW-01, JARG-01 | PASS |
| long_sentences | deliberately flawed lesson | BEGIN-02 | BEGIN-02 | PASS |
| missing_section | deliberately flawed lesson | COVER-01, COVER-02, FLOW-01 | COVER-01, COVER-02, FLOW-01 | PASS |
| idiom | deliberately flawed lesson | STYLE-01 | STYLE-01 | PASS |
| missing_limitation | deliberately flawed lesson | FLOW-01, LIMIT-01 | FLOW-01, LIMIT-01 | PASS |

## Per-check precision and recall

| Check | TP | FP | FN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| ACC-01 | 1 | 0 | 0 | 100.0% | 100.0% |
| COVER-01 | 2 | 0 | 0 | 100.0% | 100.0% |
| BEGIN-01 | 0 | 0 | 0 | n/a | n/a |
| BEGIN-02 | 1 | 0 | 0 | 100.0% | 100.0% |
| BEGIN-03 | 0 | 0 | 0 | n/a | n/a |
| BEGIN-04 | 0 | 0 | 0 | n/a | n/a |
| STYLE-01 | 1 | 0 | 0 | 100.0% | 100.0% |
| JARG-01 | 1 | 0 | 0 | 100.0% | 100.0% |
| JARG-02 | 1 | 0 | 0 | 100.0% | 100.0% |
| GLOSS-01 | 0 | 0 | 0 | n/a | n/a |
| EXAMPLE-01 | 1 | 0 | 0 | 100.0% | 100.0% |
| EXAMPLE-02 | 1 | 0 | 0 | 100.0% | 100.0% |
| EXAMPLE-03 | 1 | 0 | 0 | 100.0% | 100.0% |
| COVER-02 | 1 | 0 | 0 | 100.0% | 100.0% |
| LIMIT-01 | 1 | 0 | 0 | 100.0% | 100.0% |
| FLOW-01 | 4 | 0 | 0 | 100.0% | 100.0% |
| LENGTH-01 | 0 | 0 | 0 | n/a | n/a |

`n/a` means no fixture planted that check as a positive, so its check-specific recall is not measured.

## Interpretation and limitations

- Exact expected-check mismatches: **0**.
- This report uses deterministic mock-judge rules; it measures regression behavior, not real-model judgment quality.
- The semantic mock recognizes only the deliberately planted patterns. Passing this suite does not establish that a live judge is trustworthy on unseen lessons.
- The four good lessons are hand-authored variations of one topic and source pack, so this is a narrow calibration set.
- The wrong-order fixture also fails JARG-01 because moving the process section first exposes technical terms before their definitions.
- A live calibration run and human review are still required before making reliability claims.
