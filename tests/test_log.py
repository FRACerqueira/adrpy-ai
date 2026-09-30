
import subprocess
import sys

from adrpy.cli import init, log
from adrpy.core.errors import CommandError, UsageError

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


def test_log_leaves_a_users_own_index_as_it_is_with_a_warning(tmp_path):
    """An INDEX.md adrpy did not generate is the user's: the entry is
    written, the file is not touched, and the warning says so."""
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "INDEX.md").write_text("Our own list.\n", encoding="utf-8")

    result = log.run(_plain_entry_args(tmp_path))

    assert (folder / "2026-09-18--scope-note--lock--a-note.md").is_file()
    assert (folder / "INDEX.md").read_text(encoding="utf-8") == "Our own list.\n"
    assert any("was not written by adrpy" in warning for warning in result["warnings"])


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
    """validate_scope is not the only thing standing between a crafted --scope
    and a path escape: with validate_scope weakened to a no-op (a future
    regression, e.g. someone reusing reject_embedded_delimiter instead of
    the kebab-case check), file_path's own resolve_within call -- a second,
    independent layer, the same one new.py's file_path goes through -- still
    catches a 3-level '../' traversal that would otherwise land outside
    doc/decision-log/."""
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_log_refuses_when_folderlog_is_a_junction_onto_folderadr(tmp_path):
    """A junction aliasing folderlog onto folderadr, planted inside the
    repo tree, must be refused by log's own reject_aliased_repo_folders
    check -- no entry may land inside the decisions folder."""
    _init_repo(tmp_path)
    folderadr_dir = tmp_path / "doc" / "adr"
    folderlog_dir = tmp_path / "doc" / "decision-log"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(folderlog_dir), str(folderadr_dir)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )

    assert excinfo.value.code == "folderadr-folderlog-alias-same-directory"
    assert [p for p in folderadr_dir.glob("*.md") if p.name != "INDEX.md"] == []


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
    """If the second write (INDEX.md regeneration) fails, the entry from the
    first write is already on disk: `data.file` must name it, the same
    partial-success shape reject/supersede use for their own second-write
    failures, not a dataless generic error."""
    _init_repo(tmp_path)

    def flaky_regenerate_index(_log_dir, **_kwargs):
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


def test_log_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's "succeeded only after N attempts" message reaches this
    command's result."""
    _init_repo(tmp_path)
    real_commit_write = log.commit_write

    def flaky_commit_write(*args, **kwargs):
        real_commit_write(*args, **kwargs)
        return 3

    monkeypatch.setattr(log, "commit_write", flaky_commit_write)

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
    """The message joins every offending flag (`'/--'.join(offending)`), so
    this test passes more than one: a regression collapsing the list to just
    the first entry must not ship silently.

    Asserts the literal joined substring, not a loose 'X in str(...)' check:
    the message's static tail names every possible flag
    (front/severity/resolution/round/reopenwhen) unconditionally, so a loose
    check would pass whatever `offending` contains -- only the literal
    joined substring, which the static boilerplate can't produce on its own,
    proves the dynamic join ran."""
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
    """--front/--severity/--resolution together with a classification
    that is neither audit-finding/doc-drift nor deferred is rejected via
    `offending = provided_structured + ...` -- a future simplification
    dropping `provided_structured` from that expression would silently
    write a corrupted structured line with literal 'None' fields
    instead."""
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
    """The STRUCTURED_CLASSIFICATIONS branch's own `if provided_reopenwhen:
    raise ...` check (audit-finding/doc-drift) needs its own direct test,
    distinct from --reopenwhen's rejection on a plain classification
    (scope-note)."""
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
    """The 'forgot all three' case (the more likely real mistake), and
    the message's own join, need their own coverage distinct from the
    'missing one of three' test above, which always leaves two of the
    three present -- mutating '/--'.join(missing) to missing[0] would
    pass that test regardless."""
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
    """Asserts the message content, not just the exception type: mutating
    '/--'.join(provided_structured) to provided_structured[0] would pass
    a check that only asserts the exception type, since that mutation
    doesn't change which exception is raised, only its text."""
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


def test_log_rejects_a_whitespace_only_summary(tmp_path):
    """'--summary "   "' must not write a blank heading silently -- an
    unguarded '#    ' would parse back as an empty summary, with no
    error and no warning."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
                "--summary", "   ", "--body", "x",
            ]
        )

    assert excinfo.value.code == "field-is-blank"


def test_log_rejects_a_whitespace_only_front(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "audit-finding", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--front", "   ", "--severity", "Low", "--resolution", "Direct",
            ]
        )

    assert excinfo.value.code == "field-is-blank"


def test_log_rejects_a_whitespace_only_reopenwhen(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "deferred", "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--reopenwhen", "   ",
            ]
        )

    assert excinfo.value.code == "field-is-blank"


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


@pytest.mark.parametrize(
    "name, content",
    [
        ("not-a-real-entry-name.md", b"nothing useful\n"),
        # An interrupted earlier log's reservation (no hard links): 0 bytes.
        ("2026-09-01--scope-note--lock--earlier.md", b""),
    ],
)
@pytest.mark.parametrize("classification", ["scope-note", "retraction", "risk-accepted"])
def test_log_refuses_before_any_write_on_a_file_the_index_could_not_list(tmp_path, name, content, classification):
    """Every classification checks folderlog the way regenerating
    INDEX.md would, before the entry is written: a file there that
    would fail that regeneration refuses the call with nothing written,
    instead of writing the entry and then failing (again on every call,
    each one adding an entry)."""
    _init_repo(tmp_path)
    log_dir = tmp_path / "doc" / "decision-log"
    log_dir.mkdir(parents=True)
    (log_dir / name).write_bytes(content)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", classification, "--scope", "lock", "--slug", "x",
                "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
            ]
        )

    assert excinfo.value.code == "log-directory-contains-unrecognized-file"
    assert excinfo.value.data == {"file": name}
    assert sorted(p.name for p in log_dir.iterdir()) == [name]


def test_an_identical_retry_after_an_index_failure_still_brings_the_index_up_to_date(tmp_path, monkeypatch):
    # After log-index-regeneration-failed, the entry exists; re-running the
    # same call can only say log-entry-already-exists -- but it must still
    # leave INDEX.md listing that entry, or the index never converges.
    _init_repo(tmp_path)
    args = [
        "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock", "--slug", "x",
        "--summary", "Stranded entry", "--body", "x", "--refdate", "2026-09-18",
    ]
    real_regenerate = log.regenerate_index

    def flaky_regenerate_index(_log_dir, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(log, "regenerate_index", flaky_regenerate_index)
    with pytest.raises(CommandError):
        log.run(args)
    monkeypatch.setattr(log, "regenerate_index", real_regenerate)

    with pytest.raises(CommandError) as excinfo:
        log.run(args)

    assert excinfo.value.code == "log-entry-already-exists"
    index = (tmp_path / "doc" / "decision-log" / "INDEX.md").read_text(encoding="utf-8")
    assert "Stranded entry" in index



def test_an_already_exists_refusal_warns_when_the_index_could_not_be_regenerated(tmp_path, monkeypatch):
    # The documented recovery (an identical retry brings INDEX.md up to
    # date) must not fail silently. A file INDEX.md could not list is
    # refused before any write, so the regeneration fails here on writing.
    _init_repo(tmp_path)
    args = [
        "--path", str(tmp_path), "--classification", "scope-note", "--scope", "cli", "--slug", "other",
        "--summary", "Other", "--body", "x", "--refdate", "2026-09-18",
    ]
    log.run(args)

    def failing_regenerate_index(_log_dir, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(log, "regenerate_index", failing_regenerate_index)
    with pytest.raises(CommandError) as excinfo:
        log.run(args)

    assert excinfo.value.code == "log-entry-already-exists"
    assert any("INDEX.md" in w and "could not be regenerated" in w for w in excinfo.value.warnings)


@pytest.mark.parametrize("value", ["٤", "+4", "4_0"])
def test_round_takes_only_plain_ascii_digits(value):
    from adrpy.core.decision_log import parse_round

    with pytest.raises(CommandError) as excinfo:
        parse_round(value)

    assert excinfo.value.code == "log-round-invalid"


def _plain_entry_args(tmp_path):
    return [
        "--path", str(tmp_path),
        "--classification", "scope-note",
        "--scope", "lock",
        "--slug", "a-note",
        "--summary", "A clarifying note",
        "--body", "The body text.",
        "--refdate", "2026-09-18",
    ]


def test_log_interrupted_after_the_entry_names_the_entry_written(tmp_path, monkeypatch):
    # Ctrl+C while INDEX.md is regenerated: the entry is already on disk,
    # so the answer names it, like log-index-regeneration-failed does.
    _init_repo(tmp_path)

    def interrupted_regenerate_index(_log_dir, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(log, "regenerate_index", interrupted_regenerate_index)

    with pytest.raises(CommandError) as excinfo:
        log.run(_plain_entry_args(tmp_path))

    created = tmp_path / "doc" / "decision-log" / "2026-09-18--scope-note--lock--a-note.md"
    assert excinfo.value.code == "interrupted"
    assert excinfo.value.data == {"file": str(created)}
    assert created.is_file()


def test_log_leaves_a_users_index_that_cannot_be_read_as_it_is(tmp_path, monkeypatch):
    from adrpy.core import fs

    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "INDEX.md").write_text("Our own list.\n", encoding="utf-8")
    real_open = open

    def guarded(path, *args, **kwargs):
        if __import__("pathlib").Path(path).name == "INDEX.md":
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(fs, "open", guarded, raising=False)
    result = log.run(_plain_entry_args(tmp_path))

    assert (folder / "INDEX.md").read_text(encoding="utf-8") == "Our own list.\n"
    assert any("was not written by adrpy" in warning for warning in result["warnings"])


def test_log_regenerates_an_index_in_the_format_earlier_versions_wrote(tmp_path):
    """Positive control: the log's generated line, as every version wrote
    it, keeps the file adrpy's."""
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "INDEX.md").write_text(
        "# Decision log index\n\nGenerated -- do not edit by hand (see [the decision-log workflow](x)).\n",
        encoding="utf-8")

    log.run(_plain_entry_args(tmp_path))

    assert "2026-09-18--scope-note--lock--a-note.md" in (folder / "INDEX.md").read_text(encoding="utf-8")


def test_an_error_other_than_oserror_while_indexing_is_the_index_failure(tmp_path, monkeypatch):
    """The entry is written: any failure regenerating INDEX.md, not only an
    OSError, is log-index-regeneration-failed naming it, never interrupted."""
    _init_repo(tmp_path)
    monkeypatch.setattr(log, "regenerate_index", lambda *a, **k: (_ for _ in ()).throw(UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")))

    with pytest.raises(CommandError) as excinfo:
        log.run(_plain_entry_args(tmp_path))

    assert excinfo.value.code == "log-index-regeneration-failed"
    assert excinfo.value.data["file"].endswith("2026-09-18--scope-note--lock--a-note.md")


def test_a_colliding_entry_is_refused_whatever_the_index_rebuild_raises(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    log.run(_plain_entry_args(tmp_path))
    monkeypatch.setattr(log, "regenerate_index", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))

    with pytest.raises(CommandError) as excinfo:
        log.run(_plain_entry_args(tmp_path))

    assert excinfo.value.code == "log-entry-already-exists"
    assert any("boom" in warning for warning in excinfo.value.warnings)



def _log(tmp_path, *extra, slug="a", classification="scope-note"):
    return log.run(["--path", str(tmp_path), "--classification", classification, "--scope", "cli", "--slug", slug,
                    "--summary", "S", "--body", "b", *extra])


def _log_index(tmp_path):
    return (tmp_path / "doc" / "decision-log" / "INDEX.md").read_text(encoding="utf-8")


def test_an_entry_in_a_subfolder_is_linked_and_named_by_its_path_in_the_log(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    for sub in ("a", "b"):
        (folder / sub).mkdir()
        (folder / sub / "2026-09-01--scope-note--cli--same.md").write_text(f"# In {sub}\n", encoding="utf-8")
    _log(tmp_path, "--refdate", "2026-09-01", slug="same")
    index = _log_index(tmp_path)
    assert "(a/2026-09-01--scope-note--cli--same.md)" in index
    assert "(b/2026-09-01--scope-note--cli--same.md)" in index
    (folder / "b" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    with pytest.raises(CommandError) as raised:
        _log(tmp_path, slug="other")
    assert raised.value.data["file"] == "b/notes.md"
    assert raised.value.detail.startswith("b/notes.md ")


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="a lone surrogate is a valid name on NTFS only")
def test_an_entry_named_with_a_lone_surrogate_does_not_fail_every_later_log(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-01--scope-note--cli--x\ud800.md").write_text("# Odd \ud800 name\n", encoding="utf-8",
                                                                        errors="surrogatepass")
    result = _log(tmp_path)
    assert result["created"]
    assert "x\ufffd" in _log_index(tmp_path)


def test_log_index_cells_and_links_survive_odd_names_and_pipes(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-02--scope-note--cli--x (1) ].md").write_text("# Pipe | in | heading\n", encoding="utf-8")
    _log(tmp_path)
    row = next(line for line in _log_index(tmp_path).splitlines() if "2026-09-02" in line)
    assert "Pipe \\| in \\| heading" in row
    assert "(2026-09-02--scope-note--cli--x%20%281%29%20%5D.md)" in row
    assert "[2026-09-02--scope-note--cli--x (1) \\].md]" in row


def test_a_round_below_one_on_an_entry_is_refused_as_malformed(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-01--audit-finding--cli--neg.md").write_text(
        "# Neg\n**Front:** x | **Severity:** Low | **Resolution:** Direct | **Round:** -1\n", encoding="utf-8")
    with pytest.raises(CommandError) as raised:
        _log(tmp_path, "--front", "f", "--severity", "Low", "--resolution", "Direct", classification="audit-finding")
    assert raised.value.code == "log-directory-contains-unrecognized-file"


def test_the_log_s_own_pages_are_told_by_name_in_any_case(tmp_path):
    """The log is read in any case on every system (its `.md` too)."""
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Cycles.md").write_text("# Cycles\n", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "index.md").write_text("# Index\n", encoding="utf-8")
    assert _log(tmp_path)["created"]


def test_a_folderlog_change_names_the_log_index_left_behind(tmp_path):
    from adrpy.cli import config

    from adrpy.core.decision_log import regenerate_index

    _init_repo(tmp_path)
    (tmp_path / "doc" / "decision-log").mkdir(parents=True)
    regenerate_index(tmp_path / "doc" / "decision-log")
    result = config.run(["--path", str(tmp_path), "--folderlog", "doc/log2"])
    old = tmp_path / "doc" / "decision-log" / "INDEX.md"
    assert old.is_file()
    assert any(str(old) in warning and "previous decision-log folder" in warning for warning in result["warnings"])



def test_a_folderlog_spelled_another_way_is_not_its_own_previous_folder(tmp_path):
    from adrpy.cli import config
    from adrpy.core.decision_log import regenerate_index

    _init_repo(tmp_path)
    (tmp_path / "doc" / "decision-log").mkdir(parents=True)
    regenerate_index(tmp_path / "doc" / "decision-log")
    result = config.run(["--path", str(tmp_path), "--folderlog", "doc/../doc/decision-log"])
    assert not any("previous decision-log folder" in warning for warning in result["warnings"])


def test_a_code_span_in_a_summary_keeps_its_backslashes(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-03--scope-note--cli--code.md").write_text("# Reads `\\r\\n` endings\n", encoding="utf-8")
    _log(tmp_path)
    row = next(line for line in _log_index(tmp_path).splitlines() if "2026-09-03" in line)
    assert "`\\r\\n`" in row



def test_log_link_text_shows_a_name_with_markdown_punctuation_as_it_is(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-04--scope-note--cli--two`b_x_&amp;.md").write_text("# Odd\n", encoding="utf-8")
    _log(tmp_path)
    row = next(line for line in _log_index(tmp_path).splitlines() if "2026-09-04" in line)
    assert "[2026-09-04--scope-note--cli--two\\`b\\_x\\_\\&amp;.md]" in row


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="a lone surrogate is a valid name on NTFS only")
def test_a_lone_surrogate_is_shown_as_one_replacement_character(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-01--scope-note--cli--x\ud800y.md").write_text("# Odd\n", encoding="utf-8")
    _log(tmp_path)
    assert "x\ufffdy" in _log_index(tmp_path)
    assert "\ufffd\ufffd" not in _log_index(tmp_path)


def test_log_index_ties_are_ordered_by_path_whatever_the_system(tmp_path):
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("2026-09-05--scope-note--cli--a.md", "2026-09-05--scope-note--cli--B.md"):
        (folder / name).write_text("# t\n", encoding="utf-8")
    _log(tmp_path)
    index = _log_index(tmp_path)
    assert index.index("[2026-09-05--scope-note--cli--B.md]") < index.index("[2026-09-05--scope-note--cli--a.md]")


def test_an_entry_whose_extension_is_upper_case_is_an_entry_on_every_system(tmp_path):
    """Round allocation must not depend on the system reading the log:
    `x.MD` counts wherever it is read."""
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-09-01--audit-finding--cli--up.MD").write_text(
        "# Up\n**Front:** x | **Severity:** Low | **Resolution:** Direct | **Round:** 30\n", encoding="utf-8")
    result = _log(tmp_path, "--front", "f", "--severity", "Low", "--resolution", "Direct", classification="audit-finding")
    assert result["round"] == 31


def test_a_folderlog_respelled_as_the_same_folder_is_no_change_to_refuse(tmp_path):
    from adrpy.cli import config

    _init_repo(tmp_path)
    _log(tmp_path)
    result = config.run(["--path", str(tmp_path), "--folderlog", "doc/decision-log/../decision-log"])
    assert result["updated_fields"] == ["folderlog"]


def test_the_log_s_own_pages_in_another_case_are_its_own_on_every_system(tmp_path):
    """Its entries' `.md` is read in any case; so are INDEX.md and CYCLES.md,
    or `log` would refuse them as strays where names are case-sensitive."""
    _init_repo(tmp_path)
    folder = tmp_path / "doc" / "decision-log"
    (folder / "sub").mkdir(parents=True)
    (folder / "CYCLES.MD").write_text("# Cycles\n", encoding="utf-8")
    (folder / "sub" / "Index.Md").write_text("# Index\n", encoding="utf-8")
    assert _log(tmp_path)["created"]
