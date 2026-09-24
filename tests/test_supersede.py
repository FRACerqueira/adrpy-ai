import os
from datetime import date, timedelta
from pathlib import Path

from adrpy.cli import approve, init, new, supersede, version
from adrpy.core.errors import CommandError

import pytest


def _setup_accepted_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(
        [
            "--path",
            str(tmp_path),
            "--title",
            "Use PostgreSQL",
            "--domain",
            "Backend",
            "--scope",
            "Data",
            "--refdate",
            "2026-01-01",
        ]
    )
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    return tmp_path, adr_path


SUCCESSOR_NAME = "ADR002V01-use-postgre-sql--001.md"


def _fail_commit(monkeypatch, *, exclusive):
    """Fails the commit of the successor (created exclusively) or of the
    predecessor (replaced) -- every file is already prepared by then."""
    from adrpy.core import lifecycle

    real_commit = lifecycle.commit_write

    def failing_commit(prepared, exclusive=False, _fail=exclusive):
        if exclusive == _fail:
            raise OSError("simulated disk failure")
        return real_commit(prepared, exclusive=exclusive)

    monkeypatch.setattr(lifecycle, "commit_write", failing_commit)


def _fail_predecessor_write(monkeypatch):
    _fail_commit(monkeypatch, exclusive=False)


def test_supersede_writes_nothing_when_the_successor_write_fails(tmp_path, monkeypatch):
    """The successor is the FIRST write: its failure leaves the
    predecessor untouched, so a plain retry is always safe."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    before = adr_path.read_text(encoding="utf-8")

    _fail_commit(monkeypatch, exclusive=True)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert adr_path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "doc" / "adr" / SUCCESSOR_NAME).exists()


def test_a_failed_predecessor_write_leaves_the_successor_holding_its_number(tmp_path, monkeypatch):
    """The predecessor is the SECOND write. When it fails, the successor
    already exists on disk -- so the number the predecessor would point at
    can never be handed to an unrelated `new` in the meantime: the
    repository is inconsistent (successor-without-predecessor) and `new`
    refuses it until it is repaired by hand."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    successor_path = tmp_path / "doc" / "adr" / SUCCESSOR_NAME
    assert excinfo.value.code == "multi-file-write-partially-applied"
    assert {k: excinfo.value.data[k] for k in ("applied", "pending")} == {
        "applied": [str(successor_path)],
        "pending": [str(adr_path)],
    }
    assert excinfo.value.data["repair"]["file"] == str(adr_path)
    assert successor_path.exists()
    assert "|Superseded|Superseded" not in adr_path.read_text(encoding="utf-8")

    monkeypatch.undo()
    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Unrelated caching decision", "--refdate", "2026-01-06"])
    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [
        ("successor-without-predecessor", str(successor_path.resolve()))
    ]


def test_a_successor_of_a_different_predecessor_is_never_mistaken_for_an_orphan(tmp_path):
    # Positive control: ADR002 supersedes ADR001; superseding ADR003 must
    # create its own successor, not reuse ADR002.
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    new.run(["--path", str(tmp_path), "--title", "Use Redis", "--refdate", "2026-01-06"])
    third = tmp_path / "doc" / "adr" / "ADR003V01-use-redis.md"
    approve.run(["--file", str(third), "--refdate", "2026-01-07"])

    result = supersede.run(["--file", str(third), "--refdate", "2026-01-08"])

    assert result["created"].endswith("ADR004V01-use-redis--003.md")


def test_supersede_reports_the_colliding_filename_as_data_when_it_already_exists(tmp_path, monkeypatch):
    """Simulates the TOCTOU race file-already-exists defends against: a
    concurrent write creates the successor's target filename after this
    call's own snapshot was taken (the validated snapshot would otherwise
    always see any pre-existing file matching the naming scheme and bump
    next_number past it)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    colliding_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"

    from adrpy.core import lifecycle as lifecycle_module

    real_validate = lifecycle_module.validate_repository

    def validate_then_collide(folder, config):
        snapshot = real_validate(folder, config)
        colliding_path.write_text("already here", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(lifecycle_module, "validate_repository", validate_then_collide)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": "ADR002V01-use-postgre-sql--001.md"}


def test_supersede_happy_path(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    successor_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    assert result["created"] == str(successor_path)
    assert result["predecessor"] == str(adr_path)
    assert result["status"] == "Proposed"

    predecessor_text = adr_path.read_text(encoding="utf-8")
    assert "|Superseded|Superseded (2026-01-05) <!-- Superseded --> : 002|" in predecessor_text

    successor_text = successor_path.read_text(encoding="utf-8")
    # Title comes from the predecessor's FILENAME segment (already
    # case-transformed), not its header's prose title -- confirmed
    # against the reference tool's own live `supersede` run.
    assert "|File title md|use-postgre-sql|" in successor_text
    assert "|Domain|Backend|" in successor_text  # scope/domain inherited
    assert "|Scope|Data|" in successor_text
    assert "|Created|Proposed (2026-01-05) <!-- Proposed -->|" in successor_text


def test_supersede_with_no_title_flag_still_uses_the_predecessors_filename_segment(tmp_path):
    """Regression guard for the new --title flag: omitting it must produce
    byte-identical output to before the flag existed -- same assertions as
    test_supersede_happy_path, kept as its own test so this specific
    no-flag guarantee has a name and can't be silently lost inside a
    broader happy-path test that might get trimmed later."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    successor_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    assert result["created"] == str(successor_path)
    successor_text = successor_path.read_text(encoding="utf-8")
    assert "|File title md|use-postgre-sql|" in successor_text


def test_supersede_title_flag_overrides_the_predecessors_filename_segment(tmp_path):
    """--title's header cell holds the raw typed value, same as `new
    --title`'s own convention (confirmed against test_new.py) -- only the
    FILENAME gets case-transformed. This differs from the no-flag default
    path, where the header cell shows the case-transformed segment too,
    purely because filename_info.title is itself already a parsed,
    case-transformed value (see test_supersede_happy_path) -- not a
    convention --title is meant to replicate."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = supersede.run(
        ["--file", str(adr_path), "--refdate", "2026-01-05", "--title", "A Brand New Title"]
    )

    successor_path = tmp_path / "doc" / "adr" / "ADR002V01-a-brand-new-title--001.md"
    assert result["created"] == str(successor_path)
    successor_text = successor_path.read_text(encoding="utf-8")
    assert "|File title md|A Brand New Title|" in successor_text


def test_supersede_rejects_embedded_delimiter_in_title_flag(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05", "--title", "Bad|title"])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_supersede_rejects_a_predecessor_title_with_a_filesystem_unsafe_character(tmp_path, monkeypatch):
    """The successor's title comes from the
    predecessor's own FILENAME segment (filename_info.title), never
    delimiter-checked on read, feeding build_filename below the exact same
    way a hostile --title on `new` would. On this platform, none of the
    forbidden characters can actually appear in a real predecessor
    filename in the first place (each either fails outright or, for ':',
    collapses into an NTFS Alternate-Data-Stream instead of a literal
    filename -- confirmed live), so this drives the exact scenario a
    corrupted predecessor filename (from a different OS, or a future code
    path) would, via a monkeypatched target lookup, the same technique
    already used for migrate's own equivalent gap. Must be a per-call
    failure, not a silent forgery."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.core import lifecycle as lifecycle_module

    real_target_in = lifecycle_module._target_in

    def flaky_target_in(snapshot, path, number):
        from dataclasses import replace as replace_fields

        target = real_target_in(snapshot, path, number)
        return replace_fields(target, name=replace_fields(target.name, title="evil:hidden"))

    monkeypatch.setattr(lifecycle_module, "_target_in", flaky_target_in)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_supersede_rejects_a_predecessor_title_made_only_of_separator_characters(tmp_path, monkeypatch):
    """to_case (core/casing.py) falls back to
    echoing its raw input unchanged when word-splitting finds nothing to
    transform, which happens exactly when the title is made entirely of
    whitespace/'_'/'-' -- reachable here via a hand-edited or migrated
    predecessor filename, same technique as the filesystem-unsafe-
    character test above."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.core import lifecycle as lifecycle_module

    real_target_in = lifecycle_module._target_in

    def flaky_target_in(snapshot, path, number):
        from dataclasses import replace as replace_fields

        target = real_target_in(snapshot, path, number)
        return replace_fields(target, name=replace_fields(target.name, title="---"))

    monkeypatch.setattr(lifecycle_module, "_target_in", flaky_target_in)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_supersede_can_override_scope_and_domain(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    supersede.run(["--file", str(adr_path), "--domain", "Platform", "--scope", "Infra"])

    successor_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    text = successor_path.read_text(encoding="utf-8")
    assert "|Domain|Platform|" in text
    assert "|Scope|Infra|" in text


def test_supersede_refuses_when_a_sibling_in_the_family_is_already_superseded(tmp_path):
    """Supersede had no family-
    wide guard at all -- unlike version/revise, which both check
    has_superseded_sibling/has_pending_sibling before writing. Two
    different members of the SAME family could each be independently
    superseded, producing two live successors and two Superseded
    predecessors: exactly the corruption shape ADR001's own Decision
    Drivers name as HIGH-severity reproduced corruption, and the
    freshness fix does not close it -- freshness only protects
    the same-file race, not a second, different family member."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    # A second Accepted family member is a normal shape (version bumps
    # never retroactively touch the earlier member's own status text).
    version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])
    v02_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    approve.run(["--file", str(v02_path), "--refdate", "2026-01-04"])

    # Round 40: only the latest member (V02) can be superseded; once it is,
    # the family is frozen and superseding V01 is refused.
    supersede.run(["--file", str(v02_path), "--refdate", "2026-01-05"])

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "family-member-superseded"
    # No second successor was ever created.
    assert not (tmp_path / "doc" / "adr" / "ADR003V01-use-postgre-sql.md").exists()


def test_supersede_refuses_when_a_sibling_in_the_family_is_still_pending(tmp_path):
    """Added
    TWO co-equal guards to supersede in the same commit --
    has_superseded_sibling (covered by the test above) and
    has_pending_sibling -- but only the first ever got a test. Deleting
    the has_pending_sibling block entirely left the full suite green,
    meaning a future refactor or merge conflict could silently drop this
    guard with nothing to catch it."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    # V02 stays Proposed (never approved) -- an unresolved sibling.
    version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-04"])

    assert excinfo.value.code == "family-member-pending"
    # No write was made at all.
    assert not (tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md").exists()


def test_supersede_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """An unreadable subdirectory
    must never let this command silently treat a hidden, higher-numbered
    decision (or a hidden family member) as "not found": the one validated
    snapshot, which feeds both the family guards and the successor's
    number, refuses it (scan-incomplete)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
    assert not (adr_dir / "ADR002V01-use-postgre-sql--001.md").exists()


def test_supersede_rejects_not_yet_accepted(tmp_path):
    tmp_path = tmp_path
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Still proposed"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-still-proposed.md"

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"


def test_supersede_rejects_already_superseded(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-superseded"


def test_supersede_rejects_refdate_before_accepted_date(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-01"])

    assert excinfo.value.code == "refdate-before-history"


def test_supersede_rejects_refdate_in_future(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_supersede_rejects_embedded_delimiter_in_scope(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--scope", "Bad|scope"])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_supersede_rejects_embedded_delimiter_in_domain(tmp_path):
    """--domain needs its own '|'-rejection coverage, distinct from
    --scope's: it goes through the exact same reject_embedded_delimiter
    call one line below."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--domain", "Bad|domain"])

    assert excinfo.value.code == "field-contains-forbidden-character"


@pytest.mark.parametrize("flag", ["domain", "scope"])
def test_supersede_rejects_a_whitespace_only_value(tmp_path, flag):
    """A whitespace-only value must not be written verbatim into the
    successor's header cell."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), f"--{flag}", "   "])

    assert excinfo.value.code == "field-is-blank"


def test_supersede_does_not_claim_a_rewrite_when_it_fails_before_writing(tmp_path):
    """encoding_repaired_
    warning claims "the file has been rewritten... bytes are now lost" --
    false whenever the command fails before ever reaching its own write
    (prepare_mark_superseded, here blocked by the target still being Proposed)."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"
    assert not any("rewritten" in w.lower() for w in (excinfo.value.warnings or []))


def test_supersede_claims_the_rewrite_once_it_actually_happens(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    result = supersede.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"
    assert any("rewritten" in w.lower() for w in result["warnings"])


def test_supersede_reports_a_retry_warning_when_the_successor_write_needed_several_attempts(
    tmp_path, monkeypatch
):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage.
    The successor's commit is the exclusive one."""
    from adrpy.core import lifecycle

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    real_commit = lifecycle.commit_write

    def flaky_commit(prepared, exclusive=False):
        real_commit(prepared, exclusive=exclusive)
        return 3 if exclusive else 1

    monkeypatch.setattr(lifecycle, "commit_write", flaky_commit)

    result = supersede.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_supersede_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    assert main(["supersede", "--file", str(adr_path)]) == EXIT_SUCCESS


def test_superseding_again_after_the_successor_was_rejected_still_creates_a_new_successor(tmp_path):
    # Positive control for the orphan check: a successor rejected after a
    # SUCCESSFUL supersede (reject reverts the predecessor to Accepted)
    # also points back at the predecessor, but is the normal end of that
    # attempt, not an interrupted one -- a new supersede must just proceed.
    from adrpy.cli import reject

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    reject.run(["--file", str(tmp_path / "doc" / "adr" / SUCCESSOR_NAME), "--refdate", "2026-01-06"])

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert result["created"].endswith("ADR003V01-use-postgre-sql--001.md")


def _leave_an_orphan(tmp_path, monkeypatch, refdate="2026-01-05"):
    """A supersede whose predecessor write failed: the successor exists and
    points back, the predecessor is still Accepted."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)
    with pytest.raises(CommandError):
        supersede.run(["--file", str(adr_path), "--refdate", refdate])
    monkeypatch.undo()
    return tmp_path, adr_path, tmp_path / "doc" / "adr" / SUCCESSOR_NAME


def test_following_a_partial_supersedes_repair_literally_leaves_a_consistent_repository(tmp_path, monkeypatch):
    from adrpy.core.config import load_repo_config
    from adrpy.core.consistency import check_repository

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)
    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    monkeypatch.undo()

    repair = excinfo.value.data["repair"]
    assert repair["file"] == str(adr_path)
    assert repair["row"] in excinfo.value.detail
    label = repair["row"].split("|")[1]
    lines = adr_path.read_text(encoding="utf-8").split("\n")
    adr_path.write_text(
        "\n".join(repair["row"] if line.startswith(f"|{label}|") else line for line in lines), encoding="utf-8"
    )

    config = load_repo_config(tmp_path / "adr-config.adrplus")
    assert check_repository(adr_path.parent, config)[1] == []


def test_a_retry_after_a_partial_supersede_refuses_instead_of_guessing(tmp_path, monkeypatch):
    # The successor left by the failed predecessor write points back at a
    # predecessor that does not point at it: the repository is refused
    # until repaired by hand, so no second successor is ever created.
    tmp_path, adr_path, successor_path = _leave_an_orphan(tmp_path, monkeypatch)
    before = adr_path.read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [
        ("successor-without-predecessor", str(successor_path.resolve()))
    ]
    # The hint is a repair by hand: reject itself refuses this repository.
    assert "by hand" in excinfo.value.data["errors"][0]["hint"].lower()
    assert adr_path.read_text(encoding="utf-8") == before
    assert len(list((tmp_path / "doc" / "adr").glob("*.md"))) == 2


def test_an_undone_rejected_successor_is_not_silently_resumed_onto(tmp_path):
    # supersede -> reject the successor -> undo it leaves the same shape a
    # failed predecessor write does, with no failure at all. A new
    # supersede with a different --title must not quietly reuse it.
    from adrpy.cli import reject, undo

    # Round 40: a rejected successor is the end of its line, so the undo
    # that used to recreate this shape is refused outright.
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = tmp_path / "doc" / "adr" / SUCCESSOR_NAME
    reject.run(["--file", str(successor_path), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(successor_path)])

    assert excinfo.value.code == "rejected-successor-is-final"
    assert "|Superseded|Superseded" not in adr_path.read_text(encoding="utf-8")


def test_supersede_no_longer_takes_resume(tmp_path):
    from adrpy.core.errors import UsageError

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(UsageError):
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume"])
    assert "resume" not in {argument["name"] for argument in supersede.describe()["arguments"]}


def test_an_unreadable_file_pointing_back_is_named_in_the_error(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    broken = tmp_path / "doc" / "adr" / "ADR009V01-junk--001.md"
    broken.write_text("not a header\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [("no-header", str(broken.resolve()))]


def _hand_written_repo(tmp_path, *names):
    """Accepted decisions written straight to disk under the given names.
    Round 41: migrate refuses files carrying a supersede suffix, so a file
    pointing back from the same or a lower number can only come from an
    edit outside the tool -- written directly here."""
    from datetime import date

    from adrpy.core.config import load_repo_config
    from adrpy.core.header import DecisionRecord, build_header
    from adrpy.core.naming import parse_any_filename

    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        parsed = parse_any_filename(name, config)[1]
        record = DecisionRecord(
            number=parsed.number, title=parsed.title, version=parsed.version,
            status_create="Proposed", date_create=date(2026, 1, 1),
            status_update="Accepted", date_update=date(2026, 1, 1),
        )
        (adr_dir / name).write_bytes((build_header(config, record) + "# body\n").encode("utf-8"))
    return adr_dir


def test_a_same_family_member_is_never_a_successor(tmp_path):
    adr_dir = _hand_written_repo(tmp_path, "ADR001V01-use-x.md", "ADR001V02-use-x--001.md")
    v01 = adr_dir / "ADR001V01-use-x.md"
    before = v01.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(v01), "--refdate", "2026-01-05"])

    # Round 40: V02 (same family, newer) locks V01, which is refused before
    # any successor lookup -- either way V01 is never marked.
    assert excinfo.value.code == "not-latest-version"
    assert v01.read_bytes() == before


def test_a_lower_numbered_file_pointing_back_is_not_a_successor_and_does_not_block(tmp_path):
    adr_dir = _hand_written_repo(tmp_path, "ADR001V01-use-a--002.md", "ADR002V01-use-b.md")
    adr002 = adr_dir / "ADR002V01-use-b.md"

    result = supersede.run(["--file", str(adr002), "--refdate", "2026-01-05"])
    assert result["created"].endswith("ADR003V01-use-b--002.md")


def test_rejecting_a_successor_still_refuses_when_a_family_member_is_superseded_by_another(tmp_path):
    # A second successor naming the same predecessor, the one it does not
    # point at: the repository is refused (multiple-live-successors),
    # reject never guesses which one to revert.
    from adrpy.cli import reject

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    v02 = Path(version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"])
    approve.run(["--file", str(v02), "--refdate", "2026-01-04"])
    real_successor = Path(supersede.run(["--file", str(v02), "--refdate", "2026-01-05"])["created"])
    assert real_successor.name.startswith("ADR002")
    impostor = real_successor.with_name(real_successor.name.replace("ADR002", "ADR003", 1))
    impostor.write_bytes(real_successor.read_bytes())

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(impostor), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "repository-inconsistent"
    codes = {error["code"] for error in excinfo.value.data["errors"]}
    assert codes == {"multiple-live-successors", "successor-without-predecessor"}


def test_a_failed_predecessor_write_tells_you_how_to_repair_it(tmp_path, monkeypatch):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "multi-file-write-partially-applied"
    assert "remove the successor" in excinfo.value.detail
    assert "--resume" not in excinfo.value.detail



@pytest.mark.parametrize("command", ["approve", "reject"])
def test_the_successor_of_a_partial_supersede_is_refused_until_repaired(tmp_path, monkeypatch, command):
    # Its predecessor does not point at it (successor-without-predecessor):
    # neither approving nor rejecting it goes ahead; the repair is by hand.
    from adrpy.cli import reject

    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)
    before = orphan.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        (approve if command == "approve" else reject).run(["--file", str(orphan), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [e["code"] for e in excinfo.value.data["errors"]] == ["successor-without-predecessor"]
    assert orphan.read_bytes() == before


def test_removing_the_successor_of_a_partial_supersede_repairs_it(tmp_path, monkeypatch):
    # The repair the hint names: the successor was just created from the
    # template, so removing it restores a consistent repository and
    # supersede runs again.
    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)
    orphan.unlink()

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06"])

    assert result["created"] == str(tmp_path / "doc" / "adr" / SUCCESSOR_NAME)
    assert "|Superseded|Superseded (2026-01-06) <!-- Superseded --> : 002|" in adr_path.read_text(encoding="utf-8")


def _hand_written_proposed(adr_dir, name):
    from datetime import date

    from adrpy.core.config import load_repo_config
    from adrpy.core.header import DecisionRecord, build_header
    from adrpy.core.naming import parse_any_filename

    config = load_repo_config(adr_dir.parent.parent / "adr-config.adrplus")
    parsed = parse_any_filename(name, config)[1]
    record = DecisionRecord(number=parsed.number, title=parsed.title, version=parsed.version,
                            status_create="Proposed", date_create=date(2026, 1, 1))
    (adr_dir / name).write_bytes((build_header(config, record) + "# body\n").encode("utf-8"))
    return adr_dir / name


@pytest.mark.parametrize("name", ["ADR001V01-use-x--001.md", "ADR001V01-use-a--002.md"])
def test_a_suffix_from_the_same_or_a_higher_number_is_not_a_successor_for_any_rule(tmp_path, name):
    # Only a file with a higher number than the one its suffix names is a
    # successor (doc/lifecycle.md). A hand-made suffix pointing at its own
    # number or a later one must not trip the successor rules: approve,
    # reject, then undo all behave as for an ordinary decision.
    from adrpy.cli import reject, undo

    adr_dir = _hand_written_repo(tmp_path, "ADR002V01-use-b.md")
    target = _hand_written_proposed(adr_dir, name)

    assert approve.run(["--file", str(target), "--refdate", "2026-01-05"])["status"] == "Accepted"
    undo.run(["--file", str(target)])
    reject.run(["--file", str(target), "--refdate", "2026-01-06"])
    created = version.run(["--file", str(target), "--refdate", "2026-01-07"])["created"]
    assert Path(created).name.startswith("ADR001V02-")
