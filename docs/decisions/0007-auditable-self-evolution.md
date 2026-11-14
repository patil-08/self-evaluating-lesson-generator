# ADR 0007: Learn from repeated failures through versioned refinements

- **Status:** Accepted
- **Decision:** Persist failure patterns and feedback across runs. Repeated patterns produce logged, versioned prompt/rubric refinement candidates; apply only validated refinements and retain the mandatory hard-check contract.
- **Reason:** This provides useful learning without allowing one noisy failure or arbitrary feedback to silently weaken acceptance requirements.
- **Trade-off:** Validation adds a review step and evolution is slower than unrestricted self-editing, but changes remain explainable and reproducible.
