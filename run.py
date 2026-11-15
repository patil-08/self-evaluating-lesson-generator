"""Compatibility entry point for the packaged lesson-generator CLI."""

from __future__ import annotations

import sys

from lessongen.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
