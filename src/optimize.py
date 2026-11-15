"""Compatibility entry point for the gated lesson prompt evolution command."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lessongen.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["evolve", *sys.argv[1:]]))
