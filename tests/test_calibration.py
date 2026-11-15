from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.calibrate import run_calibration


def test_mock_calibration_matches_all_fixture_expectations(tmp_path) -> None:
    report_path = tmp_path / "calibration_report.md"

    results, report = run_calibration(output_path=report_path)

    assert len(results) == 12
    assert all(
        result.failed_checks == result.fixture.expected_failures
        for result in results
    )
    assert "True positives | 8" in report
    assert "Precision | - | 100.0%" in report
    assert "Recall | - | 100.0%" in report
    assert report_path.read_text(encoding="utf-8") == report
