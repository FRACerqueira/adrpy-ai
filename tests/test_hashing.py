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


def test_compute_hash_canonicalizes_crlf_and_lone_cr_to_lf():
    """Round 37, Class P6: content is hashed before atomic_write_text's
    own newline normalization runs, so the hash must not depend on
    whatever newline convention the content happened to arrive in."""
    assert compute_hash("line one\r\nline two\n") == compute_hash("line one\nline two\n")
    assert compute_hash("line one\rline two\n") == compute_hash("line one\nline two\n")


def test_check_drift_is_clean_for_content_that_already_contains_crlf():
    content = "line one\r\nline two\n"
    marker = build_marker("1.0.0", content)
    written = marker + "\n" + content
    assert check_drift(written) == "clean"


def test_parse_marker_ignores_a_marker_shaped_substring_not_at_the_anchor_position():
    """Round 37, Class P6: `_insert_marker` only ever places the real
    marker at position 0, or right after a leading frontmatter block --
    a marker-shaped string embedded elsewhere (hand-written, or
    copy-pasted from a generated file) must not be mistaken for it."""
    fake_marker = build_marker("9.9.9", "unrelated")
    text = f"some hand-written content\n{fake_marker}\nmore text\n"
    assert parse_marker(text) is None


def test_check_drift_is_foreign_when_a_marker_shaped_string_is_embedded_mid_body():
    fake_marker = build_marker("9.9.9", "unrelated")
    text = f"hand-written preamble\n{fake_marker}\nmore hand-written text\n"
    assert check_drift(text) == "foreign"


def test_parse_marker_still_finds_the_real_marker_after_a_frontmatter_block():
    content = "the body\n"
    marker = build_marker("1.0.0", content)
    text = f"---\nname: x\ndescription: y\n---\n{marker}\n\n{content}"
    version, digest = parse_marker(text)
    assert version == "1.0.0"
    assert digest == compute_hash(content)


def test_a_marker_after_a_later_rule_line_is_not_read_as_the_leading_marker():
    # Frontmatter ends at its FIRST closing `---` (as _insert_marker reads
    # it); a later `---` rule line must not stretch it to reach a
    # marker-shaped comment further down a hand-written file.
    text = (
        "---\ntitle: mine\n---\n\nMy notes.\n\n---\n"
        + build_marker("1.0.0", "generated body\n")
        + "\ngenerated body\n"
    )

    assert parse_marker(text) is None
    assert check_drift(text) == "foreign"


def test_a_marker_hashing_the_users_own_prefix_still_reads_as_foreign():
    prefix = "---\ntitle: mine\n---\n\nMy notes.\n\n---\n"
    rest = "\ngenerated body\n"
    text = prefix + build_marker("1.0.0", prefix + rest) + rest

    assert check_drift(text) == "foreign"


def test_a_marker_right_after_the_first_closing_rule_is_still_found():
    # Positive control: the one real placement _insert_marker uses, even
    # when the body itself contains more `---` rule lines afterwards.
    body = "\nText.\n\n---\n\nMore text.\n"
    frontmatter = "---\ntitle: x\n---\n"
    text = frontmatter + build_marker("1.0.0", frontmatter + body) + "\n" + body

    assert check_drift(text) == "clean"
