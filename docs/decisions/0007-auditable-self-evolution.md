# ADR 0007: Learn from repeated failures through versioned refinements

- **Status:** Accepted
- **Decision:** Persist failure patterns and feedback across runs. A check becomes chronic only after failures in three distinct non-mock runs under the same rubric. Create a new prompt file without overwriting prior versions, and activate it only when calibration does not regress and paired real-provider replay improves first-pass rate.
- **Reason:** Three independent runs reduce noise from deliberate injection or one poor sample. Separating mock from real evidence and requiring a paired improvement keeps prompt changes explainable and reproducible.
- **Trade-off:** Evolution requires real credentials and at least three source-compatible replay topics; otherwise the candidate is not adopted. This is slower than unrestricted self-editing, but preserves the hard rubric and avoids treating mock behavior as production evidence.
