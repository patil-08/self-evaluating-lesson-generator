"""Environment-backed settings and justified operating limits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

MAX_RETRIES = 2  # Two corrections allow recovery without an unbounded generation loop.
API_MAX_RETRIES = 3  # Three network retries cover brief provider outages without hiding failure.
API_RETRY_BASE_SECONDS = 1.0  # One second lets transient rate limits clear quickly.
API_RETRY_MAX_SECONDS = 8.0  # Capping backoff prevents a single request stalling indefinitely.
API_TIMEOUT_SECONDS = 120.0  # Allow slower live-provider responses to complete.
JUDGE_TEMPERATURE = 0.0  # Zero temperature makes hard-check judgments more repeatable.
GENERATION_TEMPERATURE = 0.3  # A little variation supports natural prose while keeping the lesson stable.
CHRONIC_FAILURE_MIN_RUNS = 3  # Three independent real runs reduce reactions to one injected failure.
MIN_REPLAY_TOPICS = 3  # Three distinct RAG topics avoid promoting a prompt from one sample.
MAX_SENTENCE_WORDS = 20  # Most lesson sentences should be short enough for a new English reader.
MAX_SENTENCE_WORDS_HARD = 30  # A hard ceiling catches severe run-ons that the ratio can miss.
MIN_SHORT_SENTENCE_RATIO = 0.9  # A 90 percent target allows a few longer quoted sentences.
MIN_READABILITY_SCORE = 60.0  # Flesch 60 is a rough screening floor, not a measure of learner ability.
MIN_LESSON_WORDS = 300  # Three hundred words leave space for steps, example, glossary, and limits.
MAX_LESSON_WORDS = 750  # Seven hundred fifty words keep a beginner lesson focused.
MAX_JARGON_DEFINITION_WORDS = 12  # A short window keeps each explanation close to first use.
MAX_PHRASAL_VERBS_PER_100_WORDS = 2.0  # Limit phrasal-verb density without banning common speech.
MIN_EXAMPLE_WORDS = 35  # A useful worked example needs a situation and an explanation.
MIN_WORKED_EXAMPLE_STEPS = 3  # Three actions demonstrate a process rather than only naming it.
MIN_GLOSSARY_TERMS = 5  # Five terms cover the core vocabulary the rubric requires.
MIN_ADVANCED_WORD_HITS = 0  # The configured difficult-word list is avoidable in learner-facing text.
MIN_REQUIRED_SECTIONS = 3  # What, why, and how are the core learning goals.

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOTENV = ROOT / ".env"


class ConfigurationError(ValueError):
    """Raised when environment settings cannot support a safe model client."""


@dataclass(frozen=True)
class Settings:
    mock_llm: bool
    api_key: str | None
    base_url: str
    gen_model: str
    judge_model: str

    def __repr__(self) -> str:
        key_status = "configured" if self.api_key else None
        return (
            "Settings("
            f"mock_llm={self.mock_llm!r}, api_key={key_status!r}, "
            f"base_url={self.base_url!r}, gen_model={self.gen_model!r}, "
            f"judge_model={self.judge_model!r})"
        )


def _read_mock_setting() -> bool:
    raw = os.getenv("MOCK_LLM", "1").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(
        "MOCK_LLM must be 1/0, true/false, yes/no, or on/off."
    )


def load_config(
    *,
    dotenv_path: str | Path | None = None,
    require_live: bool = True,
) -> Settings:
    """Load .env without overriding explicitly set process variables."""
    env_path = Path(dotenv_path) if dotenv_path is not None else DEFAULT_DOTENV
    load_dotenv(dotenv_path=env_path, override=False)

    mock_llm = _read_mock_setting()
    api_key = os.getenv("LLM_API_KEY", "").strip() or None
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    gen_model = os.getenv("GEN_MODEL", "").strip()
    judge_model = os.getenv("JUDGE_MODEL", "").strip()

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(
            "LLM_BASE_URL must be an absolute http:// or https:// URL."
        )
    if not mock_llm and require_live:
        missing = [
            name
            for name, value in (
                ("LLM_API_KEY", api_key),
                ("GEN_MODEL", gen_model),
                ("JUDGE_MODEL", judge_model),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Live mode requires "
                + ", ".join(missing)
                + ". Set them in .env or enable MOCK_LLM=1."
            )

    return Settings(
        mock_llm=mock_llm,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        gen_model=gen_model,
        judge_model=judge_model,
    )
