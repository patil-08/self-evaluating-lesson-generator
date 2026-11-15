from pathlib import Path

import pytest
from openai import APIConnectionError

from src.config import (
    API_RETRY_BASE_SECONDS,
    API_RETRY_MAX_SECONDS,
    Settings,
    load_config,
    ConfigurationError,
)
from src.llm import LLMClient, LLMError, ModelRole, parse_json_response


def mock_settings() -> Settings:
    return Settings(
        mock_llm=True,
        api_key=None,
        base_url="https://api.openai.com/v1",
        gen_model="",
        judge_model="",
    )


def live_settings() -> Settings:
    return Settings(
        mock_llm=False,
        api_key="test-key",
        base_url="https://example.test/v1",
        gen_model="writer",
        judge_model="reviewer",
    )


def test_mock_mode_returns_deterministic_role_specific_outputs() -> None:
    client = LLMClient(mock_settings())

    first = client.complete("Write a lesson", role=ModelRole.GENERATION)
    second = client.complete("A different prompt", role=ModelRole.GENERATION)
    judge = client.complete_json("Evaluate a lesson")

    assert first.content == second.content
    assert "Retrieval-Augmented Generation" in first.content
    assert first.model == "mock-generation"
    assert judge.data["passed"] is True
    assert judge.response.model == "mock-judge"
    assert client.usage.calls == 3
    assert client.usage.total_tokens == 0
    assert client.usage.latency_ms >= 0


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"passed": true}', {"passed": True}),
        ("```json\n{\"checks\": []}\n```", {"checks": []}),
        ("Result follows:\n[1, 2, 3]\nDone.", [1, 2, 3]),
    ],
)
def test_parse_json_response_handles_plain_fences_and_surrounding_text(
    text: str, expected: object
) -> None:
    assert parse_json_response(text) == expected


def test_parse_json_response_rejects_malformed_content() -> None:
    with pytest.raises(LLMError, match="did not contain valid JSON"):
        parse_json_response("```json\n{not json}\n```")


def test_live_config_requires_key_and_both_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "0")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEN_MODEL", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)

    with pytest.raises(
        ConfigurationError,
        match="LLM_API_KEY, GEN_MODEL, JUDGE_MODEL",
    ):
        load_config(dotenv_path="nonexistent-test-env")


def test_config_loads_dotenv_without_exposing_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MOCK_LLM=0\n"
        "LLM_API_KEY=local-test-secret\n"
        "LLM_BASE_URL=https://provider.example/v1/\n"
        "GEN_MODEL=writer\n"
        "JUDGE_MODEL=reviewer\n",
        encoding="utf-8",
    )
    for name in ("MOCK_LLM", "LLM_API_KEY", "LLM_BASE_URL", "GEN_MODEL", "JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)

    settings = load_config(dotenv_path=str(env_file))

    assert settings.mock_llm is False
    assert settings.api_key == "local-test-secret"
    assert settings.base_url == "https://provider.example/v1"
    assert settings.gen_model == "writer"
    assert settings.judge_model == "reviewer"
    assert "local-test-secret" not in repr(settings)


def test_invalid_mock_flag_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "sometimes")

    with pytest.raises(ConfigurationError, match="MOCK_LLM must be one of"):
        load_config(dotenv_path="nonexistent-test-env")


class FlakyCompletions:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **_: object) -> object:
        self.calls += 1
        if self.calls < 3:
            raise APIConnectionError(
                message="temporary network issue",
                request=None,  # type: ignore[arg-type]
            )
        return type(
            "Completion",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": "ready"})()},
                    )()
                ],
                "usage": type(
                    "Usage",
                    (),
                    {"prompt_tokens": 4, "completion_tokens": 2},
                )(),
            },
        )()


class FakeClient:
    def __init__(self) -> None:
        self.completions = FlakyCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


def test_live_client_retries_transient_errors_with_exponential_backoff() -> None:
    fake_client = FakeClient()
    delays: list[float] = []
    client = LLMClient(
        live_settings(),
        client=fake_client,
        sleep_fn=delays.append,
    )

    response = client.complete("prompt", role=ModelRole.GENERATION)

    assert response.content == "ready"
    assert response.model == "writer"
    assert response.prompt_tokens == 4
    assert response.completion_tokens == 2
    assert response.latency_ms >= 0
    assert fake_client.completions.calls == 3
    assert delays == [
        API_RETRY_BASE_SECONDS,
        min(API_RETRY_BASE_SECONDS * 2, API_RETRY_MAX_SECONDS),
    ]
    assert client.usage.total_tokens == 6


def test_live_client_reports_error_after_retry_limit() -> None:
    class AlwaysFails:
        calls = 0

        def create(self, **_: object) -> object:
            self.calls += 1
            raise APIConnectionError(message="offline", request=None)  # type: ignore[arg-type]

    completions = AlwaysFails()
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
    client = LLMClient(live_settings(), client=fake_client, sleep_fn=delays.append)

    with pytest.raises(LLMError, match="failed after 3 retries"):
        client.complete("prompt")

    assert completions.calls == 4
    assert delays == [
        API_RETRY_BASE_SECONDS,
        API_RETRY_BASE_SECONDS * 2,
        API_RETRY_BASE_SECONDS * 4,
    ]
