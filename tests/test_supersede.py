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


def _fail_predecessor_write(monkeypatch):
    from adrpy.cli import supersede as supersede_module

    def failing_mark(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(supersede_module, "mark_superseded", failing_mark)


def test_supersede_writes_nothing_when_the_successor_write_fails(tmp_path, monkeypatch):
    """The successor is the FIRST write: its failure leaves the
    predecessor untouched, so a plain retry is always safe."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    before = adr_path.read_text(encoding="utf-8")

    from adrpy.cli import supersede as supersede_module

    def flaky_write(path, content):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(supersede_module, "atomic_write_text", flaky_write)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert adr_path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "doc" / "adr" / SUCCESSOR_NAME).exists()


def test_a_failed_predecessor_write_leaves_the_successor_holding_its_number(tmp_path, monkeypatch):
    """The predecessor is the SECOND write. When it fails, the successor
    already exists on disk -- so the number the predecessor would point at
    can never be handed to an unrelated `new` in the meantime (the old
    order left the predecessor pointing at ': 002' with no ADR002 on disk,
    and the next `new` took 002)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    successor_path = tmp_path / "doc" / "adr" / SUCCESSOR_NAME
    assert excinfo.value.code == "supersede-write-failed"
    assert excinfo.value.data["successor"] == str(successor_path)
    assert excinfo.value.data["predecessor_status"] == "Accepted"
    assert successor_path.exists()
    assert "|Superseded|Superseded" not in adr_path.read_text(encoding="utf-8")

    monkeypatch.undo()
    result = new.run(["--path", str(tmp_path), "--title", "Unrelated caching decision", "--refdate", "2026-01-06"])
    assert result["created"].endswith("ADR003V01-unrelated-caching-decision.md")


def test_retrying_after_a_failed_predecessor_write_resumes_instead_of_creating_a_second_successor(
    tmp_path, monkeypatch
):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)
    with pytest.raises(CommandError):
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    monkeypatch.undo()
    successor_path = tmp_path / "doc" / "adr" / SUCCESSOR_NAME
    successor_before = successor_path.read_text(encoding="utf-8")

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume"])

    assert result["created"] == str(successor_path)
    assert any("resumed" in warning for warning in result["warnings"])
    assert "|Superseded|Superseded (2026-01-06) <!-- Superseded --> : 002|" in adr_path.read_text(encoding="utf-8")
    assert successor_path.read_text(encoding="utf-8") == successor_before
    assert sorted(p.name for p in (tmp_path / "doc" / "adr").glob("*.md")) == [
        "ADR001V01-use-postgre-sql.md",
        SUCCESSOR_NAME,
    ]


def test_an_orphaned_successor_that_moved_on_is_not_resumed(tmp_path, monkeypatch):
    """Only a successor still Proposed -- untouched since the interrupted
    call -- is resumed. One already approved or rejected in the meantime
    is refused rather than guessed at."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)
    with pytest.raises(CommandError):
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    monkeypatch.undo()
    successor_path = tmp_path / "doc" / "adr" / SUCCESSOR_NAME
    _approve_as_a_pre_round_41_repository_could_have(successor_path, "2026-01-06", monkeypatch)
    predecessor_before = adr_path.read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-07", "--resume"])

    assert excinfo.value.code == "supersede-orphaned-successor-not-resumable"
    assert excinfo.value.data["file"] == str(successor_path)
    assert adr_path.read_text(encoding="utf-8") == predecessor_before


def test_a_successor_of_a_different_predecessor_is_never_mistaken_for_an_orphan(tmp_path):
    # Positive control: ADR002 supersedes ADR001; superseding ADR003 must
    # create its own successor, not resume onto ADR002.
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    new.run(["--path", str(tmp_path), "--title", "Use Redis", "--refdate", "2026-01-06"])
    third = tmp_path / "doc" / "adr" / "ADR003V01-use-redis.md"
    approve.run(["--file", str(third), "--refdate", "2026-01-07"])

    result = supersede.run(["--file", str(third), "--refdate", "2026-01-08"])

    assert result["created"].endswith("ADR004V01-use-redis--003.md")
    assert not any("resumed" in warning for warning in result["warnings"])


def test_supersede_reports_the_colliding_filename_as_data_when_it_already_exists(tmp_path, monkeypatch):
    """Simulates the TOCTOU race file-already-exists defends against: a
    concurrent write creates the successor's target filename after this
    call's own scan already took its snapshot (the scan itself would
    otherwise always see any pre-existing file matching the naming scheme
    and bump next_number past it)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    colliding_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    colliding_path.write_text("already here", encoding="utf-8")

    from adrpy.cli import supersede as supersede_module

    real_scan_decisions = supersede_module.scan_decisions

    def scan_without_colliding_file(folder, config, warnings=None, **kwargs):
        return [entry for entry in real_scan_decisions(folder, config) if entry[2].name != colliding_path.name]

    monkeypatch.setattr(supersede_module, "scan_decisions", scan_without_colliding_file)

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
    path) would, via a monkeypatched load_target, the same technique
    already used for migrate's own equivalent gap. Must be a per-call
    failure, not a silent forgery."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    real_load_target = supersede_module.load_target

    def flaky_load_target(fileadr, warnings=None):
        config, root, path, filename_info, header, encoding_repaired = real_load_target(fileadr, warnings=warnings)
        from dataclasses import replace as replace_fields

        return config, root, path, replace_fields(filename_info, title="evil:hidden"), header, encoding_repaired

    monkeypatch.setattr(supersede_module, "load_target", flaky_load_target)

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

    from adrpy.cli import supersede as supersede_module

    real_load_target = supersede_module.load_target

    def flaky_load_target(fileadr, warnings=None):
        config, root, path, filename_info, header, encoding_repaired = real_load_target(fileadr, warnings=warnings)
        from dataclasses import replace as replace_fields

        return config, root, path, replace_fields(filename_info, title="---"), header, encoding_repaired

    monkeypatch.setattr(supersede_module, "load_target", flaky_load_target)

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
    decision (or a hidden family member) as "not found". supersede's own
    family_members() call (feeding has_superseded_sibling/has_pending_
    sibling) reads the SAME folder earlier IN THIS COMMAND'S OWN CONTROL
    FLOW than the successor-number scan, and is strict too -- given a
    genuinely unreadable subdirectory (as opposed to one that becomes
    unreadable only in the narrow window between the two scans), it
    deterministically fires first every time. The separate, independent
    wiring of the later successor-number scan's own incomplete_code is
    proven on its own terms by the companion test right below ."""
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

    assert excinfo.value.code == "family-scan-incomplete"
    assert not (adr_dir / "ADR002V01-use-postgre-sql--001.md").exists()


def test_supersede_successor_number_scan_wires_its_own_incomplete_code(tmp_path, monkeypatch):
    """Precise companion to the test above: family_members() reads the
    SAME folder earlier and always fires first for a genuinely unreadable
    subdirectory, which could make the later, independent
    supersede-successor-scan-incomplete path look unreachable/dead.
    Proves it isn't -- patches only supersede.py's own direct
    scan_decisions call (family_members uses lifecycle.py's own
    reference, untouched here), confirming this command really does wire
    its own incomplete_code into that second, independent scan."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    def failing_scan_decisions(folder, config, warnings=None, **kwargs):
        raise CommandError(kwargs.get("incomplete_code", "scan-incomplete"), "simulated incomplete scan", warnings=warnings)

    monkeypatch.setattr(supersede_module, "scan_decisions", failing_scan_decisions)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-scan-incomplete"


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
    (mark_superseded, here blocked by the target still being Proposed)."""
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
    supersede.py imports and calls atomic_write_text directly for the
    SUCCESSOR write (unlike the predecessor's own mark_superseded write,
    which goes through core.lifecycle's own reference)."""
    from adrpy.cli import supersede as supersede_module

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    real_atomic_write_text = supersede_module.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(supersede_module, "atomic_write_text", flaky_atomic_write_text)

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
    assert not any("resumed" in warning for warning in result["warnings"])


def test_a_rejected_earlier_successor_does_not_stop_resuming_onto_the_new_orphan(tmp_path, monkeypatch):
    from adrpy.cli import reject

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    reject.run(["--file", str(tmp_path / "doc" / "adr" / SUCCESSOR_NAME), "--refdate", "2026-01-06"])
    _fail_predecessor_write(monkeypatch)
    with pytest.raises(CommandError):
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-07"])
    monkeypatch.undo()

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-08", "--resume"])

    assert result["created"].endswith("ADR003V01-use-postgre-sql--001.md")
    assert any("resumed" in warning for warning in result["warnings"])
    assert "|Superseded|Superseded (2026-01-08) <!-- Superseded --> : 003|" in adr_path.read_text(encoding="utf-8")


def _approve_as_a_pre_round_41_repository_could_have(path, refdate, monkeypatch):
    """Round 41 (K2a) refuses approving the successor of an unfinished
    supersede; repositories from before that rule -- or hand edits -- can
    still hold one, and the recovery advice below must work for them. The
    setup approves it with that one check switched off."""
    from adrpy.cli import approve as approve_module

    with monkeypatch.context() as scoped:
        scoped.setattr(approve_module, "raise_if_supersede_not_finished", lambda *args, **kwargs: None)
        approve.run(["--file", str(path), "--refdate", refdate])


def _leave_an_orphan(tmp_path, monkeypatch, refdate="2026-01-05"):
    """A supersede whose predecessor write failed: the successor exists and
    points back, the predecessor is still Accepted."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)
    with pytest.raises(CommandError):
        supersede.run(["--file", str(adr_path), "--refdate", refdate])
    monkeypatch.undo()
    return tmp_path, adr_path, tmp_path / "doc" / "adr" / SUCCESSOR_NAME


def test_a_retry_without_resume_refuses_instead_of_guessing(tmp_path, monkeypatch):
    tmp_path, adr_path, successor_path = _leave_an_orphan(tmp_path, monkeypatch)
    before = adr_path.read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "supersede-successor-already-exists"
    assert excinfo.value.data["file"] == str(successor_path)
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


def test_resume_refuses_successor_content_flags_it_would_otherwise_ignore(tmp_path, monkeypatch):
    from adrpy.core.errors import UsageError

    tmp_path, adr_path, _successor_path = _leave_an_orphan(tmp_path, monkeypatch)

    for flag in (["--title", "Other"], ["--scope", "Other"], ["--domain", "Other"]):
        with pytest.raises(UsageError):
            supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume", *flag])


def test_resume_refuses_a_refdate_before_the_successors_own_creation(tmp_path, monkeypatch):
    tmp_path, adr_path, _successor_path = _leave_an_orphan(tmp_path, monkeypatch, refdate="2026-01-20")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-10", "--resume"])

    assert excinfo.value.code == "refdate-before-history"
    assert "|Superseded|Superseded" not in adr_path.read_text(encoding="utf-8")


def test_resume_with_nothing_to_resume_is_refused(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05", "--resume"])

    assert excinfo.value.code == "supersede-orphaned-successor-not-resumable"
    assert excinfo.value.data["files"] == []
    assert len(list((tmp_path / "doc" / "adr").glob("*.md"))) == 1


def test_resume_refuses_more_than_one_orphan_and_names_them_all(tmp_path, monkeypatch):
    tmp_path, adr_path, first = _leave_an_orphan(tmp_path, monkeypatch)
    second = tmp_path / "doc" / "adr" / "ADR003V01-use-postgre-sql--001.md"
    second.write_bytes(first.read_bytes().replace(b"ADR002", b"ADR003").replace(b"|002|", b"|003|"))
    names_before = sorted(p.name for p in (tmp_path / "doc" / "adr").glob("*.md"))

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume"])

    assert excinfo.value.code == "supersede-orphaned-successor-not-resumable"
    assert sorted(excinfo.value.data["files"]) == sorted([str(first), str(second)])
    assert sorted(p.name for p in (tmp_path / "doc" / "adr").glob("*.md")) == names_before


def test_resume_refuses_a_successor_with_no_creation_status(tmp_path, monkeypatch):
    # A migrated placeholder carries the supersede suffix but no Created
    # status/date of its own: nothing proves it came from an interrupted
    # supersede of this decision.
    tmp_path, adr_path, successor_path = _leave_an_orphan(tmp_path, monkeypatch)
    text = successor_path.read_text(encoding="utf-8")
    created_row = [line for line in text.splitlines() if line.startswith("|Created|")][0]
    successor_path.write_text(text.replace(created_row, "|Created||"), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume"])

    assert excinfo.value.code == "supersede-orphaned-successor-not-resumable"
    assert "|Superseded|Superseded" not in adr_path.read_text(encoding="utf-8")


def test_an_unreadable_file_pointing_back_is_named_in_the_error(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    broken = tmp_path / "doc" / "adr" / "ADR009V01-junk--001.md"
    broken.write_text("not a header\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.data["file"] == str(broken)


def test_an_orphan_approved_since_is_recovered_by_undo_then_resume(tmp_path, monkeypatch):
    # The recovery path the refusal messages name: neither reject nor
    # --resume accepts an Accepted successor, so undo comes first.
    from adrpy.cli import reject, undo

    tmp_path, adr_path, successor_path = _leave_an_orphan(tmp_path, monkeypatch)
    _approve_as_a_pre_round_41_repository_could_have(successor_path, "2026-01-06", monkeypatch)
    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path), "--refdate", "2026-01-07"])
    assert excinfo.value.code == "already-accepted"

    undo.run(["--file", str(successor_path)])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-07", "--resume"])

    assert result["created"] == str(successor_path)
    assert "|Superseded|Superseded (2026-01-07) <!-- Superseded --> : 002|" in adr_path.read_text(encoding="utf-8")


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


def test_a_file_pointing_at_its_own_number_is_never_resumed_onto_itself(tmp_path):
    # A successor always gets a later number than its predecessor; a file
    # whose suffix names its own number is not a successor at all.
    adr_dir = _hand_written_repo(tmp_path, "ADR001V01-use-x--001.md")
    target = adr_dir / "ADR001V01-use-x--001.md"
    before = target.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(target), "--refdate", "2026-01-05", "--resume"])

    assert excinfo.value.code == "supersede-orphaned-successor-not-resumable"
    assert target.read_bytes() == before


def test_a_same_family_member_is_never_a_successor(tmp_path):
    adr_dir = _hand_written_repo(tmp_path, "ADR001V01-use-x.md", "ADR001V02-use-x--001.md")
    v01 = adr_dir / "ADR001V01-use-x.md"
    before = v01.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(v01), "--refdate", "2026-01-05", "--resume"])

    # Round 40: V02 (same family, newer) locks V01, which is refused before
    # any successor lookup -- either way V01 is never marked.
    assert excinfo.value.code == "not-latest-version"
    assert v01.read_bytes() == before


def test_a_lower_numbered_file_pointing_back_is_not_a_successor_and_does_not_block(tmp_path):
    adr_dir = _hand_written_repo(tmp_path, "ADR001V01-use-a--002.md", "ADR002V01-use-b.md")
    adr002 = adr_dir / "ADR002V01-use-b.md"

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr002), "--refdate", "2026-01-05", "--resume"])
    assert excinfo.value.code == "supersede-orphaned-successor-not-resumable"

    result = supersede.run(["--file", str(adr002), "--refdate", "2026-01-05"])
    assert result["created"].endswith("ADR003V01-use-b--002.md")


def test_the_refusal_for_nothing_to_resume_says_so(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05", "--resume"])

    assert "without --resume" in excinfo.value.detail


def test_rejecting_a_successor_still_refuses_when_a_family_member_is_superseded_by_another(tmp_path):
    # Positive control: a family member IS Superseded, pointing at some
    # other successor -- which member this one came from is ambiguous, so
    # reject still refuses rather than guess.
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

    assert excinfo.value.code == "superseded-predecessor-not-found"


def test_following_the_no_created_status_advice_recovers(tmp_path, monkeypatch):
    # The message must name a step that works: reject can't act on a file
    # with no Created status, so the only ways out are by hand.
    tmp_path, adr_path, successor_path = _leave_an_orphan(tmp_path, monkeypatch)
    text = successor_path.read_text(encoding="utf-8")
    created_row = [line for line in text.splitlines() if line.startswith("|Created|")][0]
    successor_path.write_text(text.replace(created_row, "|Created||"), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume"])
    assert "delete it and run supersede without --resume" in excinfo.value.detail

    successor_path.unlink()
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06"])
    assert Path(result["created"]).name == "ADR002V01-use-postgre-sql--001.md"


def test_following_the_superseded_since_advice_recovers_when_its_successor_was_approved(tmp_path, monkeypatch):
    from adrpy.cli import reject, undo

    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)
    _approve_as_a_pre_round_41_repository_could_have(orphan, "2026-01-06", monkeypatch)
    second = Path(supersede.run(["--file", str(orphan), "--refdate", "2026-01-07"])["created"])
    approve.run(["--file", str(second), "--refdate", "2026-01-08"])

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-09", "--resume"])
    assert "undo that successor first if it was approved" in excinfo.value.detail

    undo.run(["--file", str(second)])
    reject.run(["--file", str(second), "--refdate", "2026-01-09"])
    undo.run(["--file", str(orphan)])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-09", "--resume"])
    assert result["created"] == str(orphan)


def test_the_already_exists_advice_covers_an_approved_successor_further_down_the_chain(tmp_path, monkeypatch):
    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "supersede-successor-already-exists"
    assert "undo that successor first if it was approved" in excinfo.value.detail
    assert "repeat down the chain" in excinfo.value.detail


def test_the_not_resumable_reasons_name_the_step_that_fixes_them(tmp_path, monkeypatch):
    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)
    _approve_as_a_pre_round_41_repository_could_have(orphan, "2026-01-06", monkeypatch)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-07", "--resume"])

    assert "undo it back to Proposed" in excinfo.value.detail


def test_a_failed_predecessor_write_tells_you_to_resume(tmp_path, monkeypatch):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    _fail_predecessor_write(monkeypatch)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-write-failed"
    assert "supersede --resume" in excinfo.value.detail



@pytest.mark.parametrize("command", ["approve", "version"])
def test_an_unfinished_supersede_must_be_finished_before_its_successor_moves_on(tmp_path, monkeypatch, command):
    # Round 41 (K2a): the successor of an interrupted supersede can't be
    # approved (or branched) while its predecessor doesn't point at it --
    # that would leave two live lines; finish with --resume, or reject it.
    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)
    if command == "version":
        _approve_as_a_pre_round_41_repository_could_have(orphan, "2026-01-06", monkeypatch)
    before = orphan.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        if command == "approve":
            approve.run(["--file", str(orphan), "--refdate", "2026-01-06"])
        else:
            version.run(["--file", str(orphan), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "supersede-not-finished"
    assert excinfo.value.data["predecessor_number"] == 1
    assert orphan.read_bytes() == before


def test_after_resume_the_successor_can_be_approved(tmp_path, monkeypatch):
    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-06", "--resume"])

    assert approve.run(["--file", str(orphan), "--refdate", "2026-01-07"])["status"] == "Accepted"


def test_an_unfinished_successor_can_still_be_rejected(tmp_path, monkeypatch):
    from adrpy.cli import reject

    tmp_path, adr_path, orphan = _leave_an_orphan(tmp_path, monkeypatch)

    assert reject.run(["--file", str(orphan), "--refdate", "2026-01-06"])["status"] == "Rejected"


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
