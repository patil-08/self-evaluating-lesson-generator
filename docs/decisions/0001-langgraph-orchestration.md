# ADR 0001: Use LangGraph for bounded lesson orchestration

- **Status:** Accepted
- **Decision:** Represent generation, evaluation, rejection logging, and retry as explicit graph nodes and conditional edges.
- **Reason:** The graph makes state transitions and the retry boundary inspectable and testable, matching the assignment's agentic workflow.
- **Trade-off:** Adds a framework dependency compared with a plain loop; the visible graph and bounded state machine justify that cost.
