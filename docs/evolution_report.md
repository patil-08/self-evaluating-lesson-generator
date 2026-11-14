# Prompt Evolution Report

- Generated: 2026-11-14T18:31:16+00:00
- Active prompt: `1.0` (`lesson_generation_v1.txt`)
- Chronic failure threshold: at least 3 distinct non-mock runs for one check and rubric version.
- Threshold rationale: three independent real runs reduce the chance that one injected flaw, transient response, or single unusual lesson drives a persistent prompt change.

## Observed first-pass performance and retries

| Data type | Prompt version | Runs | First-pass rate | Total retries |
| --- | --- | ---: | ---: | ---: |
| Mock (not real) | `1.0` | 4 | 2/4 (50%) | 2 |
| Real provider | — | 0 | not measured (no live run history) | 0 |

## Chronic failures

No hard check reached the chronic-failure threshold in real runs.

## Calibration gate

- Deterministic mock suite: **PASS** (4/4 good lessons pass; 17/17 expected flaw checks caught; 204/204 per-check outcomes match).
- Any candidate changes only generator instructions, not rubric v1. The same evaluator contract and fixture suite must remain fully passing.

## Paired replay gate

- Not run: live provider settings are not enabled; fewer than 3 eligible prior RAG topics. Found 0 real run(s) and 0 eligible topic(s).

## Candidate and decision

- Candidate: not generated.
- Decision: **not proposed: no check failed in three distinct real runs; the available mock history includes an injected flaw**.

## Data labels and limits

Mock history is shown separately and is never counted toward the chronic-failure threshold or described as real-provider evidence. Run-history rates are descriptive, not paired counterfactuals; only the paired replay can justify adoption.
The local evaluator's cited facts cover RAG. Non-RAG topics are not eligible for prompt replay until matching reviewed source facts are added.
