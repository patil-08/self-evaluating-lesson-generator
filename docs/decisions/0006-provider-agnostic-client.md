# ADR 0006: Use an OpenAI-compatible provider interface with offline mock mode

- **Status:** Accepted
- **Decision:** Configure the API key, base URL, generation model, and judge model through environment variables; provide a deterministic mock mode for tests and offline demos.
- **Reason:** The same interface supports compatible endpoints without embedding credentials or binding the application to a single provider.
- **Trade-off:** Provider-specific features are out of scope; errors and structured output must be normalized by the client wrapper.
