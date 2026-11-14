"""Versioned active generator-prompt selection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"
ACTIVE_PROMPT_FILE = PROMPTS_DIR / "active_generator.json"
DEFAULT_PROMPT_VERSION = "1.0"
DEFAULT_PROMPT_FILE = "lesson_generation_v1.txt"
_VERSION_RE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class PromptSpec:
    version: str
    path: Path


def _validate_spec(version: object, filename: object) -> PromptSpec:
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ValueError("Active generator prompt version must use MAJOR.MINOR format.")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("Active generator prompt must be a file name in prompts/.")
    prompts_dir = PROMPTS_DIR.resolve()
    path = (PROMPTS_DIR / filename).resolve()
    if path.parent != prompts_dir or not path.is_file():
        raise ValueError(
            f"Active generator prompt file does not exist inside prompts/: {filename!r}."
        )
    return PromptSpec(version=version, path=path)


def get_active_prompt() -> PromptSpec:
    """Read the active pointer, falling back to the original v1 prompt."""
    if not ACTIVE_PROMPT_FILE.exists():
        return _validate_spec(DEFAULT_PROMPT_VERSION, DEFAULT_PROMPT_FILE)
    try:
        pointer = json.loads(ACTIVE_PROMPT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read active prompt pointer: {error}") from error
    if not isinstance(pointer, dict):
        raise ValueError("Active prompt pointer must contain a JSON object.")
    return _validate_spec(pointer.get("version"), pointer.get("file"))


def select_prompt(
    *,
    version: str | None = None,
    path: str | Path | None = None,
) -> PromptSpec:
    """Select an explicit replay prompt or the currently active version."""
    if version is None and path is None:
        return get_active_prompt()
    if version is None or path is None:
        raise ValueError("Prompt replay requires both a version and a prompt path.")
    selected_path = Path(path).resolve()
    if selected_path.parent != PROMPTS_DIR.resolve() or not selected_path.is_file():
        raise ValueError("Selected generator prompt must be an existing file in prompts/.")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Generator prompt version must use MAJOR.MINOR format.")
    return PromptSpec(version=version, path=selected_path)


def activate_prompt(spec: PromptSpec) -> None:
    """Atomically switch the active pointer without altering prior prompt files."""
    validated = _validate_spec(spec.version, spec.path.name)
    temporary_path = ACTIVE_PROMPT_FILE.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(
            {"version": validated.version, "file": validated.path.name},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(ACTIVE_PROMPT_FILE)
