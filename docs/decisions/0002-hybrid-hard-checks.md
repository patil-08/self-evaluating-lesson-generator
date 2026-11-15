# ADR 0002: Combine deterministic checks with a structured LLM judge

- **Status:** Accepted
- **Decision:** Enforce objective requirements in code and use a separate judge prompt for meaning, accuracy against sources, and teaching flow. Each rubric dimension is binary; any mandatory failure rejects the lesson.
- **Reason:** Code is repeatable for observable constraints, while semantic qualities need language understanding. A score cannot compensate for a missing requirement.
- **Trade-off:** The judge may still be inconsistent; structured evidence, source grounding, mock tests, and retained results make its decisions reviewable.
