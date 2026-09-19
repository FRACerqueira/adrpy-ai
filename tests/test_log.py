from adrpy.cli import init, log
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.lock import LockLostError

import pytest


def _init_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    return tmp_path


def test_log_writes_a_plain_entry_with_no_structured_line(tmp_path):
    _init_repo(tmp_path)

    result = log.run(
        [
            "--path", str(tmp_path),
            "--classification", "scope-note",
            "--scope", "lock",
            "--slug", "a-note",
            "--summary", "A clarifying note",
            "--body", "The body text.",
            "--refdate", "2026-09-18",
        ]
    )

    created = tmp_path / "doc" / "decision-log" / "2026-09-18--scope-note--lock--a-note.md"
    assert result["created"] == str(created)
    assert result["round"] is None
    text = created.read_text(encoding="utf-8")
    assert text == "# A clarifying note\n\nThe body text.\n"


def test_log_writes_an_audit_finding_with_the_structured_line_and_computes_round(tmp_path):
    _init_repo(tmp_path)

    result = log.run(
        [
            "--path", str(tmp_path),
            "--classification", "audit-finding",
            "--scope", "lock",
            "--slug", "found-a-bug",
            "--summary", "Found and fixed a bug",
            "--body", "Details.",
            "--front", "smoke test",
            "--severity", "Medium",
            "--resolution", "Direct",
            "--refdate", "2026-09-18",
        ]
    )

    assert result["round"] == 1
    created = tmp_path / "doc" / "decision-log" / "2026-09-18--audit-finding--lock--found-a-bug.md"
    text = created.read_text(encoding="utf-8")
    assert "**Front:** smoke test | **Severity:** Medium | **Resolution:** Direct | **Round:** 1" in text


def test_log_computes_the_next_round_across_a_second_call(tmp_path):
    _init_repo(tmp_path)
    log.run(
        [
            "--path", str(tmp_path), "--classification", "doc-drift", "--scope", "lock", "--slug", "first",
            "--summary", "First", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
        ]
    )

    result = log.run(
        [
            "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "config", "--slug", "second",
            "--summary", "Second", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
        ]
    )

    assert result["round"] == 2


def test_log_writes_a_deferred_entry_with_reopenwhen(tmp_path):
    _init_repo(tmp_path)

    result = log.run(
        [
            "--path", str(tmp_path),
            "--classification", "deferred",
            "--scope", "lock",
            "--slug", "postponed",
            "--summary", "Postponed for now",
            "--body", "Reason.",
            "--reopenwhen", "when X happens",
            "--refdate", "2026-09-18",
        ]
    )

    assert result["round"] is None
    created = tmp_path / "doc" / "decision-log" / "2026-09-18--deferred--lock--postponed.md"
    text = created.read_text(encoding="utf-8")
    assert "**Reopen-when:** when X happens" in text


def test_log_regenerates_the_index_as_part_of_the_same_write(tmp_path):
    _init_repo(tmp_path)

    log.run(
        [
            "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "a-note",
            "--summary", "A note", "--body", "x", "--refdate", "2026-09-18",
        ]
    )

    index_text = (tmp_path / "doc" / "decision-log" / "INDEX.md").read_text(encoding="utf-8")
    assert "2026-09-18--scope-note--lock--a-note.md" in index_text


def test_log_refuses_a_colliding_filename_without_writing(tmp_path):
    _init_repo(tmp_path)
    kwargs = [
        "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "dup",
        "--summary", "First", "--body", "x", "--refdate", "2026-09-18",
    ]
    log.run(kwargs)

    with pytest.raises(CommandError) as excinfo:
        log.run(kwargs)

    assert excinfo.value.code == "log-entry-already-exists"
    assert excinfo.value.data == {"file": "2026-09-18--scope-note--lock--dup.md"}


def test_log_rejects_an_invalid_classification(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "not-real", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )

    assert excinfo.value.code == "log-classification-invalid"


def test_log_rejects_a_non_kebab_case_slug(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "Not_Kebab",
                "--summary", "x", "--body", "x",
            ]
        )

    assert excinfo.value.code == "log-slug-invalid"


@pytest.mark.parametrize("missing", ["front", "severity", "resolution"])
def test_log_requires_all_three_structured_fields_together_for_audit_finding(tmp_path, missing):
    _init_repo(tmp_path)
    fields = {"front": "x", "severity": "Low", "resolution": "Direct"}
    del fields[missing]
    args = ["--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
            "--summary", "x", "--body", "x"]
    for name, value in fields.items():
        args += [f"--{name}", value]

    with pytest.raises(UsageError):
        log.run(args)


def test_log_rejects_reopenwhen_on_a_classification_that_does_not_use_it(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(UsageError):
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--reopenwhen", "x",
            ]
        )


def test_log_rejects_structured_fields_on_deferred(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(UsageError):
        log.run(
            [
                "--path", str(tmp_path), "--classification", "deferred", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--reopenwhen", "x", "--front", "x",
            ]
        )


def test_log_rejects_a_deferred_entry_missing_reopenwhen(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(UsageError):
        log.run(
            [
                "--path", str(tmp_path), "--classification", "deferred", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )


def test_log_rejects_a_non_kebab_case_scope(tmp_path):
    """scope becomes a literal filename segment -- '|' (and '/', '\\',
    a double-hyphen) is rejected by the same kebab-case check as slug,
    not merely by the generic forbidden-delimiter check summary uses."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock|bad", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )
    assert excinfo.value.code == "log-scope-invalid"


def test_log_never_writes_outside_the_decision_log_directory_even_if_scope_validation_is_bypassed(
    tmp_path, monkeypatch
):
    """Round-13 corroboration: validate_scope alone is not the only thing
    standing between a crafted --scope and a path escape -- confirmed by
    weakening validate_scope to a no-op (simulating a future regression,
    e.g. someone reusing reject_embedded_delimiter instead of the
    kebab-case check) and showing file_path's own resolve_within call
    (a second, independent layer, the same one new.py's own file_path
    already goes through) still catches a 3-level '../' traversal that
    would otherwise land outside doc/decision-log/ entirely."""
    _init_repo(tmp_path)
    monkeypatch.setattr(log, "validate_scope", lambda value: None)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "../../../escaped",
                "--slug", "x", "--summary", "x", "--body", "SECRET CONTENT",
            ]
        )

    assert excinfo.value.code == "path-outside-repository"
    # Confirms the escape genuinely didn't happen -- not just that some
    # error was raised.
    assert not any(tmp_path.rglob("*escaped*"))


def test_log_rejects_forbidden_character_in_summary(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "bad|summary", "--body", "x",
            ]
        )
    assert excinfo.value.code == "field-contains-forbidden-character"


def test_log_aborts_if_folderadr_changed_after_lock_acquired(tmp_path, monkeypatch):
    """Same freshness requirement as every other write command (ADR001
    part 2, applied to this command's own lock use)."""
    _init_repo(tmp_path)
    stale_config = load_repo_config(tmp_path / "adr-config.adrplus")

    from adrpy.cli import config as config_module

    config_module.run(["--path", str(tmp_path), "--folderadr", "doc/adrB"])

    monkeypatch.setattr(log, "load_repo_config", lambda path: stale_config)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert not (tmp_path / "doc" / "decision-log").exists()


def test_log_refdate_defaults_to_today(tmp_path):
    from datetime import date

    _init_repo(tmp_path)

    result = log.run(
        [
            "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
            "--summary", "x", "--body", "x",
        ]
    )

    assert date.today().isoformat() in result["created"]


def test_log_reports_the_entry_already_written_when_index_regeneration_fails(tmp_path, monkeypatch):
    """Second write in the same critical section (ADR001, part 3): if it
    fails, the entry from the FIRST write is already committed to disk
    for real -- `data.file` must name it explicitly, the same
    partial-success shape reject/supersede already use for their own
    second-write failures, not a dataless generic error."""
    _init_repo(tmp_path)

    def flaky_regenerate_index(_log_dir):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(log, "regenerate_index", flaky_regenerate_index)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
            ]
        )

    assert excinfo.value.code == "log-index-regeneration-failed"
    created = tmp_path / "doc" / "decision-log" / "2026-09-18--scope-note--lock--x.md"
    assert excinfo.value.data == {"file": str(created)}
    assert created.exists()  # the entry write itself really did succeed


def test_log_rejects_a_future_refdate(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--refdate", "2099-01-01",
            ]
        )

    assert excinfo.value.code == "refdate-in-future"


def test_log_reports_lock_lost_the_same_way_as_an_oserror_during_index_regeneration(tmp_path, monkeypatch):
    """The exact regression class this codebase already hit once, in
    supersede.py (tests/test_supersede.py's own
    test_supersede_reveals_predecessor_already_superseded_when_the_lock_is_lost_before_the_successor_write):
    an `except OSError` alone silently bypasses the partial-success
    handler for a LockLostError on this same second write. Confirms the
    handler's `except (OSError, LockLostError)` tuple actually covers
    both, not just the one exercised by the sibling OSError test above."""
    _init_repo(tmp_path)

    def flaky_regenerate_index(_log_dir):
        raise LockLostError("simulated lock loss")

    monkeypatch.setattr(log, "regenerate_index", flaky_regenerate_index)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
            ]
        )

    assert excinfo.value.code == "log-index-regeneration-failed"
    created = tmp_path / "doc" / "decision-log" / "2026-09-18--scope-note--lock--x.md"
    assert excinfo.value.data == {"file": str(created)}
    assert created.exists()


def test_log_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own "succeeded only after N attempts" message had
    no end-to-end coverage for this command -- every sibling write
    command has this test; log was the only one missing it."""
    _init_repo(tmp_path)
    real_atomic_write_text = log.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(log, "atomic_write_text", flaky_atomic_write_text)

    result = log.run(
        [
            "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
            "--summary", "x", "--body", "x",
        ]
    )

    assert any("3 attempts" in w for w in result["warnings"])


def test_log_warns_when_round_is_auto_assigned_with_no_prior_round(tmp_path):
    _init_repo(tmp_path)

    result = log.run(
        [
            "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
            "--summary", "x", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
        ]
    )

    assert result["round"] == 1
    assert len(result["warnings"]) == 1
    assert "auto-assigned" in result["warnings"][0]
    assert "no prior round exists" in result["warnings"][0]


def test_log_warns_and_suggests_reuse_when_round_is_auto_assigned_with_a_prior_round_open(tmp_path):
    _init_repo(tmp_path)
    log.run(
        [
            "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "first",
            "--summary", "First", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
            "--round", "1",
        ]
    )

    result = log.run(
        [
            "--path", str(tmp_path), "--classification", "doc-drift", "--scope", "config", "--slug", "second",
            "--summary", "Second", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
        ]
    )

    assert result["round"] == 2
    assert len(result["warnings"]) == 1
    assert "Round 2 was auto-assigned" in result["warnings"][0]
    assert "--round 1" in result["warnings"][0]


def test_log_accepts_an_explicit_round_with_no_warning_and_no_increment(tmp_path):
    _init_repo(tmp_path)
    log.run(
        [
            "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "first",
            "--summary", "First", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
            "--round", "1",
        ]
    )

    result = log.run(
        [
            "--path", str(tmp_path), "--classification", "doc-drift", "--scope", "config", "--slug", "second",
            "--summary", "Second", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
            "--round", "1",
        ]
    )

    assert result["round"] == 1
    assert result["warnings"] == []


def test_log_rejects_an_explicit_round_lower_than_the_current_max(tmp_path):
    _init_repo(tmp_path)
    log.run(
        [
            "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "first",
            "--summary", "First", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
            "--round", "5",
        ]
    )

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "doc-drift", "--scope", "config", "--slug", "second",
                "--summary", "Second", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
                "--round", "3",
            ]
        )

    assert excinfo.value.code == "log-round-too-low"
    assert excinfo.value.data == {"round": 3, "current_max": 5}


def test_log_rejects_a_non_positive_integer_round(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
                "--round", "0",
            ]
        )

    assert excinfo.value.code == "log-round-invalid"


def test_log_rejects_round_on_a_classification_that_does_not_use_it(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(UsageError):
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--round", "1",
            ]
        )


def test_log_names_every_offending_flag_when_more_than_one_is_wrong_at_once(tmp_path):
    """Round-13 corroboration: every existing 'wrong flag for this
    classification' test passes exactly one offending flag -- the message
    joins ALL of them (`'/--'.join(offending)`), but nothing had ever
    exercised more than one at a time, so a regression collapsing the
    list to just the first entry would have shipped silently.

    Round-14 corroboration found THIS test was itself vacuous: the
    message's own static tail already names every possible flag
    (front/severity/resolution/round/reopenwhen) unconditionally, so
    loose 'X in str(...)' checks pass regardless of what `offending`
    actually contains -- confirmed by mutating '/--'.join(offending) to
    offending[0] and observing this test still passed. Asserts the
    literal joined substring instead, which only the real dynamic join
    (not the static boilerplate) can produce."""
    _init_repo(tmp_path)

    with pytest.raises(UsageError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--round", "1", "--reopenwhen", "x",
            ]
        )

    assert "--round/--reopenwhen" in str(excinfo.value)


def test_log_rejects_a_lone_structured_field_on_a_plain_classification(tmp_path):
    """Round-15 Test-Adequacy: no existing test ever passed --front/
    --severity/--resolution together with a classification that is
    neither audit-finding/doc-drift nor deferred. The current code
    already rejects it via `offending = provided_structured + ...`, but
    nothing proved that -- a future simplification dropping
    `provided_structured` from that expression would silently write a
    corrupted structured line with literal 'None' fields instead."""
    _init_repo(tmp_path)
    log_dir = tmp_path / "doc" / "decision-log"

    with pytest.raises(UsageError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--front", "corrupt-me",
            ]
        )

    assert "--front" in str(excinfo.value)
    if log_dir.exists():
        assert not any(log_dir.glob("*.md"))


def test_log_rejects_reopenwhen_on_audit_finding(tmp_path):
    """Round-15 Test-Adequacy: --reopenwhen's rejection is only ever
    tested against a plain classification (scope-note); the
    STRUCTURED_CLASSIFICATIONS branch's own `if provided_reopenwhen:
    raise ...` check (audit-finding/doc-drift) had never been exercised."""
    _init_repo(tmp_path)

    with pytest.raises(UsageError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
                "--front", "x", "--severity", "Low", "--resolution", "Direct", "--reopenwhen", "x",
            ]
        )

    assert "--reopenwhen" in str(excinfo.value)


def test_log_names_all_three_structured_fields_when_none_are_provided(tmp_path):
    """Round-15 Test-Adequacy: the only existing 'missing structured
    field' test always leaves two of the three present -- the 'forgot
    all three' case (the more likely real mistake) and the message's own
    join were both untested. Mutating '/--'.join(missing) to missing[0]
    would have passed every existing test."""
    _init_repo(tmp_path)

    with pytest.raises(UsageError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )

    assert "--front/--severity/--resolution" in str(excinfo.value)


def test_log_names_every_offending_structured_field_on_deferred(tmp_path):
    """Round-15 Test-Adequacy: the only existing 'structured field on
    deferred' test passes just --front and asserts only the exception
    type, never the message -- mutating '/--'.join(provided_structured)
    to provided_structured[0] would have passed regardless."""
    _init_repo(tmp_path)

    with pytest.raises(UsageError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "deferred", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--reopenwhen", "x", "--front", "x", "--severity", "Low",
            ]
        )

    assert "--front/--severity" in str(excinfo.value)


def test_log_rejects_round_on_deferred(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(UsageError):
        log.run(
            [
                "--path", str(tmp_path), "--classification", "deferred", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--reopenwhen", "x", "--round", "1",
            ]
        )


def test_log_rejects_severity_not_in_the_closed_set(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--front", "x", "--severity", "Critical", "--resolution", "Direct",
            ]
        )

    assert excinfo.value.code == "log-severity-invalid"


def test_log_rejects_resolution_not_in_the_closed_set(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Maybe",
            ]
        )

    assert excinfo.value.code == "log-resolution-invalid"


def test_log_rejects_forbidden_character_in_front(tmp_path):
    """front/severity/resolution are all embedded directly into the
    entry's own '|'-delimited structured line and into INDEX.md's own
    '|'-delimited table row -- but severity/resolution are also
    constrained to a closed set (tested separately above), which already
    excludes '|' by construction. front is the one free-text field of
    the three, so it's the one this specific check is actually reachable
    through."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
                "--front", "bad|front", "--severity", "Low", "--resolution", "Direct",
            ]
        )

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_log_rejects_forbidden_character_in_reopenwhen(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "deferred", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--reopenwhen", "bad|reopenwhen",
            ]
        )

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_log_reports_target_directory_not_found():
    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", "does-not-exist-anywhere", "--classification", "scope-note", "--scope", "lock",
                "--slug", "x", "--summary", "x", "--body", "x",
            ]
        )

    assert excinfo.value.code == "target-directory-not-found"


def test_log_reports_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )

    assert excinfo.value.code == "config-not-found"


def test_log_fails_before_any_write_on_an_unrecognized_file_for_a_structured_classification(tmp_path):
    """audit-finding/doc-drift scan the directory for max_existing_round
    BEFORE writing anything -- an unrecognized file there is caught at
    that point, cleanly, with no entry ever written."""
    _init_repo(tmp_path)
    log_dir = tmp_path / "doc" / "decision-log"
    log_dir.mkdir(parents=True)
    (log_dir / "not-a-real-entry-name.md").write_text("nothing useful\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--front", "x", "--severity", "Low", "--resolution", "Direct",
            ]
        )

    assert excinfo.value.code == "log-directory-contains-unrecognized-file"
    assert not any(p.name.endswith("--lock--x.md") for p in log_dir.glob("*.md"))


def test_log_reports_the_entry_already_written_when_an_unrecognized_file_blocks_index_regeneration(tmp_path):
    """For a non-structured classification, the directory is only ever
    scanned during index regeneration -- AFTER the entry write already
    committed. An unrecognized file there is still caught, but as a
    log-index-regeneration-failed partial success (same shape as the
    OSError/LockLostError cases), not a clean pre-write refusal -- this
    is genuinely different from the structured-classification case
    above, not an inconsistency to paper over."""
    _init_repo(tmp_path)
    log_dir = tmp_path / "doc" / "decision-log"
    log_dir.mkdir(parents=True)
    (log_dir / "not-a-real-entry-name.md").write_text("nothing useful\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
            ]
        )

    assert excinfo.value.code == "log-index-regeneration-failed"
    created = log_dir / "2026-09-18--scope-note--lock--x.md"
    assert excinfo.value.data == {"file": str(created)}
    assert created.exists()  # the entry write itself really did succeed
    assert "not-a-real-entry-name.md" in excinfo.value.detail  # the underlying cause is still named
