from adrpy.cli import init, log
from adrpy.core.config import load_repo_config
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


def test_log_rejects_forbidden_character_in_scope_or_summary(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        log.run(
            [
                "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock|bad", "--slug", "x",
                "--summary", "x", "--body", "x",
            ]
        )
    assert excinfo.value.code == "field-contains-forbidden-character"

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
