"""Compatibility wrapper for the packaged calibration command."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lessongen.calibration import main, run_calibration

__all__ = ["run_calibration"]


if __name__ == "__main__":
    raise SystemExit(main())
