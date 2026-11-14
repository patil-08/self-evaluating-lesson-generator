from scripts.calibrate import load_fixtures


def test_calibration_manifest_has_four_good_and_eight_flawed_lessons() -> None:
    fixtures = load_fixtures()

    assert len(fixtures) == 12
    assert sum(fixture.expected_pass for fixture in fixtures) == 4
    assert sum(not fixture.expected_pass for fixture in fixtures) == 8
    assert all(
        fixture.expected_fail_checks
        for fixture in fixtures
        if not fixture.expected_pass
    )


def test_declared_calibration_mutations_produce_the_named_flaws() -> None:
    fixtures = {fixture.id: fixture for fixture in load_fixtures()}

    assert "RAG guarantees" in fixtures["flaw-false-claim"].lesson
    assert "cosine similarity" in fixtures["flaw-unexplained-jargon"].lesson
    assert "Everyday worked example" not in fixtures["flaw-no-example"].lesson
    assert (
        fixtures["flaw-wrong-order"].lesson.index("## Why does RAG matter?")
        < fixtures["flaw-wrong-order"].lesson.index("## How does RAG work?")
    )
    assert "Limits" not in fixtures["flaw-missing-limitation"].lesson
