import os
import time
from datetime import date, timedelta

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


def test_supersede_reveals_predecessor_already_superseded_when_successor_write_fails(tmp_path, monkeypatch):
    """Mechanism-correctness audit (resilience finding #1), the
    worst instance found: supersede marks the predecessor Superseded
    (mark_superseded, a real committed write) BEFORE writing the
    successor. If only the successor write fails with a real OSError, the
    predecessor is left permanently Superseded with no successor ever
    created -- an orphaned, broken family state. The failure response
    must name that partial mutation explicitly via `data`, not just
    convert to the generic io-error the attach_warnings safety net alone
    would produce."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    def flaky_write(path, content):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(supersede_module, "atomic_write_text", flaky_write)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert excinfo.value.data["predecessor"] == str(adr_path)
    assert excinfo.value.data["predecessor_status"] == "Superseded"
    # The predecessor really was mutated on disk despite the overall failure.
    assert "|Superseded|Superseded" in adr_path.read_text(encoding="utf-8")


def test_supersede_reveals_predecessor_already_superseded_when_the_lock_is_lost_before_the_successor_write(
    tmp_path, monkeypatch
):
    """Same partial-mutation risk as
    the OSError test above, but for LockLostError on this command's
    SECOND write -- it must not bypass supersede-successor-write-failed's
    handler (which only catches OSError), or a caller would see the
    generic, dataless 'no write was made' lock-lost message even though
    the predecessor was already, for real, committed to Superseded."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    real_build_header = supersede_module.build_header

    def steal_lock_then_build(*args, **kwargs):
        lock_path = tmp_path / "doc" / "adr" / ".adrpy.lock"
        lock_path.write_text(f"someone-else-entirely\n{time.time()}")
        return real_build_header(*args, **kwargs)

    monkeypatch.setattr(supersede_module, "build_header", steal_lock_then_build)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert excinfo.value.data["predecessor"] == str(adr_path)
    assert excinfo.value.data["predecessor_status"] == "Superseded"
    # The predecessor really was mutated on disk despite the overall failure.
    assert "|Superseded|Superseded" in adr_path.read_text(encoding="utf-8")


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
    """A round-22 security finding: the successor's title comes from the
    predecessor's own FILENAME segment (filename_info.title), never
    delimiter-checked on read, feeding build_filename below the exact same
    way a hostile --title on `new` would. On this platform, none of the
    forbidden characters can actually appear in a real predecessor
    filename in the first place (each either fails outright or, for ':',
    collapses into an NTFS Alternate-Data-Stream instead of a literal
    filename -- confirmed live), so this drives the exact scenario a
    corrupted predecessor filename (from a different OS, or a future code
    path) would, via a monkeypatched read_target, the same technique
    already used for migrate's own equivalent gap. Must be a per-call
    failure, not a silent forgery."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    real_read_target = supersede_module.read_target

    def flaky_read_target(path, config, warnings=None):
        filename_info, header, encoding_repaired = real_read_target(path, config, warnings=warnings)
        from dataclasses import replace as replace_fields

        return replace_fields(filename_info, title="evil:hidden"), header, encoding_repaired

    monkeypatch.setattr(supersede_module, "read_target", flaky_read_target)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_supersede_rejects_a_predecessor_title_made_only_of_separator_characters(tmp_path, monkeypatch):
    """A round-23 security finding: to_case (core/casing.py) falls back to
    echoing its raw input unchanged when word-splitting finds nothing to
    transform, which happens exactly when the title is made entirely of
    whitespace/'_'/'-' -- reachable here via a hand-edited or migrated
    predecessor filename, same technique as the filesystem-unsafe-
    character test above."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    real_read_target = supersede_module.read_target

    def flaky_read_target(path, config, warnings=None):
        filename_info, header, encoding_repaired = real_read_target(path, config, warnings=warnings)
        from dataclasses import replace as replace_fields

        return replace_fields(filename_info, title="---"), header, encoding_repaired

    monkeypatch.setattr(supersede_module, "read_target", flaky_read_target)

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

    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(v02_path), "--refdate", "2026-01-06"])

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
