import httpx
import pytest
from openai import RateLimitError

from lessongen.config import Settings
from lessongen.llm import LLMClient, LLMError


def test_live_client_does_not_retry_provider_quota_errors() -> None:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )
    quota_error = RateLimitError(
        "daily quota exceeded",
        response=response,
        body={"error": {"message": "daily quota exceeded"}},
    )

    class QuotaLimitedCompletions:
        calls = 0

        def create(self, **_: object) -> object:
            self.calls += 1
            raise quota_error

    completions = QuotaLimitedCompletions()
    fake_client = type(
        "Client",
        (),
        {
            "chat": type(
                "Chat",
                (),
                {"completions": completions},
            )()
        },
    )()
    delays: list[float] = []
    settings = Settings(
        mock_llm=False,
        api_key="test-key",
        base_url="https://example.test/v1",
        gen_model="writer",
        judge_model="reviewer",
    )
    client = LLMClient(settings, client=fake_client, sleep_fn=delays.append)

    with pytest.raises(LLMError, match="failed after 1 attempt"):
        client.complete("prompt")

    assert completions.calls == 1
    assert delays == []
