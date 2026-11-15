# ADR 0005: Persist run memory in SQLite

- **Status:** Accepted
- **Decision:** Store run outcomes, rejection categories, user feedback, and memory schema/version metadata in a local SQLite database.
- **Reason:** SQLite persists across runs, works offline, has no service to operate, and supports auditable queries for this single-user take-home.
- **Trade-off:** It is not intended for concurrent multi-user deployment; database files remain local and are git-ignored.
