# ADR 0003: Limit generation to two retries

- **Status:** Accepted
- **Decision:** Allow one first draft plus at most two retries.
- **Reason:** Two correction opportunities can address feedback without an open-ended cost or latency loop.
- **Trade-off:** A difficult lesson can end in failure. The system reports that failure and all rejection reasons rather than claiming success.
