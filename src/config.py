"""Environment-backed settings and shared lesson/evaluation limits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

# Two regeneration opportunities are enough for corrective feedback while
# bounding graph cost; the initial draft makes three total lesson attempts.
MAX_RETRIES = 2

# Keep sentences short enough for beginner-facing material without enforcing
# unnatural one-clause prose.
MAX_SENTENCE_WORDS = 20
# One concrete example is the minimum useful anchor for an abstract topic.
MIN_EXAMPLES = 1
# These are the three learning questions explicitly required by the assignment.
MIN_REQUIRED_SECTIONS = 3
# At least nine in ten sentences should meet the target; a single short quote
# should not fail a lesson with otherwise readable prose.
MIN_SHORT_SENTENCE_RATIO = 0.9
# A 30-word hard ceiling catches severe run-ons beyond the preferred 20 words.
MAX_SENTENCE_WORDS_HARD = 30
# Flesch 60 is a broad "plain English" floor, paired with stronger learner checks.
MIN_READABILITY_SCORE = 60.0
# Do not allow the small curated advanced-word blacklist in learner-facing text.
MAX_ADVANCED_VOCABULARY_HITS = 0
# At most two listed phrasal verbs per 100 words avoids phrasal-verb-heavy prose.
MAX_PHRASAL_VERBS_PER_100_WORDS = 2.0
# Define a technical term within twelve following words so the explanation stays close.
MAX_JARGON_DEFINITION_WORDS = 12
# 250 words leaves room for what/why/how, a worked example, and a glossary.
MIN_LESSON_WORDS = 250
# 650 words keeps a beginner lesson focused and manageable.
MAX_LESSON_WORDS = 650
# A short example needs enough room to show a situation and the answer path.
MIN_EXAMPLE_WORDS = 35
# Three visible ordered actions demonstrate a process, not only an analogy.
MIN_WORKED_EXAMPLE_STEPS = 3
# Five learner-relevant terms cover the key vocabulary introduced by this topic.
MIN_GLOSSARY_TERMS = 5

# Three retries tolerate brief provider outages without hiding persistent errors.
API_MAX_RETRIES = 3
# A one-second first wait gives transient rate limits time to clear quickly.
API_RETRY_BASE_SECONDS = 1.0
# Capping the wait keeps one lesson request from stalling for too long.
API_RETRY_MAX_SECONDS = 8.0
# Thirty seconds is a practical upper bound for a single generation/judge call.
API_TIMEOUT_SECONDS = 30.0

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class ConfigurationError(ValueError):
    """Raised when environment settings cannot support a safe LLM client."""


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings; credentials are never included in repr."""

    mock_llm: bool
    api_key: str | None
    base_url: str
    gen_model: str
    judge_model: str

    def __repr__(self) -> str:
        return (
            "Settings("
            f"mock_llm={self.mock_llm!r}, "
            f"api_key={'configured' if self.api_key else None!r}, "
            f"base_url={self.base_url!r}, "
            f"gen_model={self.gen_model!r}, "
            f"judge_model={self.judge_model!r})"
        )


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"{name} must be one of 1/0, true/false, yes/no, or on/off; "
        f"received {raw_value!r}."
    )


def load_config(
    *,
    dotenv_path: str | None = None,
    require_live: bool = True,
) -> Settings:
    """Load `.env`; callers may defer live-credential checks to choose mock mode."""
    load_dotenv(dotenv_path=dotenv_path, override=False)

    mock_llm = _read_bool("MOCK_LLM", default=True)
    api_key = os.getenv("LLM_API_KEY", "").strip() or None
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    gen_model = os.getenv("GEN_MODEL", "").strip()
    judge_model = os.getenv("JUDGE_MODEL", "").strip()

    if not base_url:
        raise ConfigurationError("LLM_BASE_URL must not be empty.")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
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
            names = ", ".join(missing)
            raise ConfigurationError(
                f"Live LLM mode requires {names}. Set them in .env or the "
                "process environment, or set MOCK_LLM=1 for offline use."
            )

    return Settings(
        mock_llm=mock_llm,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        gen_model=gen_model,
        judge_model=judge_model,
    )
