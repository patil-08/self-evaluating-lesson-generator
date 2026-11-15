"""Compatibility import for the packaged LangGraph workflow."""

from __future__ import annotations

from lessongen.config import MAX_RETRIES, load_config
from lessongen.graph import build as build_workflow
from lessongen.llm import LLMClient


def build(*, max_retries: int = MAX_RETRIES, inject_error: str | None = None):
    settings = load_config(require_live=False)
    return build_workflow(
        client=LLMClient(settings=settings),
        max_retries=max_retries,
        inject_error=inject_error,
    )
