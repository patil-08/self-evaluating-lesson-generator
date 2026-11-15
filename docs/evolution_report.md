## Evolution evaluation — 2026-11-15T13:33:14.703877+00:00

- **Decision:** INELIGIBLE
- **Replay mode:** not run
- **Candidate prompt:** not created
- **Rubric candidate:** none
- **Chronic-failure threshold:** 3 distinct real runs
- **Replay-topic minimum:** 3 distinct topics

### Chronic failures from real history

- No chronic real-run failure met the threshold.

### Recorded production history (real runs only)

- Runs: 0
- First-pass rate: n/a (no recorded real runs)
- Total retries: 0

### Candidate replay comparison

| Replay | First-pass rate | Retries | Runs |
| --- | ---: | ---: | ---: |
| Replay not run | n/a | n/a | n/a |

### Calibration guard (mock fixtures)

| Version | Exact fixture matches | Mismatches | Fixtures |
| --- | ---: | ---: | ---: |
| Before (mock calibration) | 12 | 0 | 12 |

- Calibration gate: **NOT RUN**.
- First-pass improvement gate: **NOT RUN**.

Mock replay results are explicitly labeled and never authorize adoption. No rubric change was proposed; rubric version remains unchanged.

## Historical legacy-implementation snapshot (2026-11-14)

The original `main` branch recorded four **mock** runs for prompt version `1.0`:
first-pass rate 2/4 (50%) and two total retries. It recorded zero real-provider
runs and did not generate or adopt a candidate. This is a separate historical
run set from the current report above; the mock runs are not real evidence and
the figures must not be added together.
