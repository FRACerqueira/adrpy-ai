from adrpy.core.hashing import build_marker, check_drift, compute_hash, parse_marker, strip_marker


def test_compute_hash_is_deterministic_and_sensitive_to_content():
    assert compute_hash("hello") == compute_hash("hello")
    assert compute_hash("hello") != compute_hash("hello ")


def test_build_marker_round_trips_through_parse_marker():
    marker = build_marker("1.2.3", "some content")
    version, digest = parse_marker(marker)
    assert version == "1.2.3"
    assert digest == compute_hash("some content")


def test_parse_marker_returns_none_when_absent():
    assert parse_marker("just some text, no marker here") is None


def test_strip_marker_is_the_exact_inverse_of_inserting_marker_plus_newline():
    content = "line one\nline two\n"
    marker = build_marker("1.0.0", content)
    written = marker + "\n" + content
    assert strip_marker(written) == content


def test_check_drift_absent_when_nothing_exists():
    assert check_drift(None) == "absent"


def test_check_drift_foreign_when_no_marker_present():
    assert check_drift("hand-written content with no marker") == "foreign"


def test_check_drift_clean_when_content_matches_recorded_hash():
    content = "the generated body\n"
    marker = build_marker("1.0.0", content)
    written = marker + "\n" + content
    assert check_drift(written) == "clean"


def test_check_drift_drifted_when_content_no_longer_matches():
    content = "the generated body\n"
    marker = build_marker("1.0.0", content)
    written = marker + "\n" + content
    hand_edited = written.replace("generated body", "HAND-EDITED body")
    assert check_drift(hand_edited) == "drifted"
