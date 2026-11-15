from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from lessongen.config import ConfigurationError, Settings, load_config
from lessongen.llm import LLMClient, LLMError, ModelRole, parse_json_response


def _mock_settings() -> Settings:
    return Settings(True, None, "https://api.openai.com/v1", "", "")


def test_mock_generation_is_deterministic_and_tracks_usage() -> None:
    client = LLMClient(settings=_mock_settings())

    first = client.complete("write a lesson")
    second = client.complete("write a lesson")

    assert first.content == second.content
    assert "Introduction to RAG" in first.content
    assert client.usage.calls == 2
    assert client.usage.total_tokens == 0


@pytest.mark.parametrize(
    "text",
    [
        '{"ok": true}',
        '```json\n{"ok": true}\n```',
        'Result follows: {"ok": true} thanks.',
    ],
)
def test_json_parser_handles_plain_fenced_and_surrounded_json(text: str) -> None:
    assert parse_json_response(text) == {"ok": True}


def test_json_parser_surfaces_invalid_data() -> None:
    with pytest.raises(LLMError, match="valid JSON"):
        parse_json_response("not json")


def test_config_reports_invalid_mock_value(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MOCK_LLM", "sometimes")

    with pytest.raises(ConfigurationError, match="MOCK_LLM"):
        load_config(dotenv_path=tmp_path / "missing.env")


def test_live_config_error_lists_missing_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MOCK_LLM", "0")
    for key in ("LLM_API_KEY", "GEN_MODEL", "JUDGE_MODEL"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigurationError) as error:
        load_config(dotenv_path=tmp_path / "missing.env")

    assert "LLM_API_KEY" in str(error.value)
    assert "GEN_MODEL" in str(error.value)
    assert "JUDGE_MODEL" in str(error.value)


def test_transient_connection_error_retries_with_exponential_backoff() -> None:
    sleeps: list[float] = []
    attempts = 0

    def create(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise APIConnectionError(request=httpx.Request("POST", "https://test"))
        usage = SimpleNamespace(prompt_tokens=7, completion_tokens=4)
        message = SimpleNamespace(content="answer")
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice], usage=usage)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )
    settings = Settings(False, "fake-key", "https://test/v1", "gen", "judge")
    client = LLMClient(settings=settings, client=fake_client, sleep_fn=sleeps.append)

    result = client.complete("prompt", role=ModelRole.GENERATION)

    assert attempts == 3
    assert sleeps == [1.0, 2.0]
    assert result.content == "answer"
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 4
    assert client.usage.calls == 1


def test_mock_judge_returns_structured_json() -> None:
    client = LLMClient(settings=_mock_settings())
    prompt = (
        "Evaluation input:\n"
        + json.dumps(
            {
                "lesson": "RAG means Retrieval-Augmented Generation.",
                "hard_checks": [
                    {
                        "check_id": "ACC-01",
                        "dimension": "accurate_and_grounded",
                    }
                ],
            }
        )
    )

    data, _response = client.complete_json(prompt)

    assert data["checks"][0]["check_id"] == "ACC-01"
