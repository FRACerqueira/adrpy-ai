"""Shared lifecycle-transition helpers (harness Fase 7): date-reference
validation, title-uniqueness/next-number resolution, and the read-mutate-
rewrite mechanics every status-transition command
(approve/reject/undo/supersede/version/revise) shares -- one function per
concern, not copies (Fase 1)."""

import os
import re
from datetime import date as date_cls
from pathlib import Path

from adrpy.core.atomic_write import atomic_write_text, split_real_lines
from adrpy.core.casing import unique_title_key
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import HEADER_LINE_COUNT, DecisionRecord, build_header, counts_as_family_member, parse_header
from adrpy.core.io_retry import read_with_permission_retry
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import find_unreadable_subdirectories, is_within
from adrpy.core.warnings import excluded_candidate_warning


def parse_refdate(text):
    """Shared `--refdate` parsing: defaults to today when omitted, else
    strict ISO (YYYY-MM-DD)."""
    if not text:
        return date_cls.today()
    try:
        return date_cls.fromisoformat(text)
    except ValueError as error:
        raise CommandError("refdate-invalid-format", f"Invalid date: {text}") from error


def validate_refdate_not_in_future(refdate):
    """Mirrors Helper.ValidateRefDateNotInFuture."""
    if refdate > date_cls.today():
        raise CommandError("refdate-in-future", f"Reference date {refdate.isoformat()} is in the future.")


def validate_refdate_not_before(refdate, not_before):
    """Mirrors Helper.ValidateRefDateNotBefore."""
    if refdate < not_before:
        raise CommandError(
            "refdate-before-history",
            f"Reference date {refdate.isoformat()} is before {not_before.isoformat()}.",
        )


def scan_decisions(folder, config, warnings=None):
    """Recognizes BOTH naming schemes (Fase 6 checklist) -- every command
    that resolves "next number" or "does this title already exist" must
    consider legacy files too. Returns a list of (scheme, ParsedFileName,
    path) for every recognized file under `folder`.

    When `warnings` is given, reports (round 4 observability audit,
    Finding 3) any candidate is_within excluded because its real path
    escapes `folder`'s boundary -- previously silent, indistinguishable
    from "no such file" to every caller."""
    if not folder.is_dir():
        return []
    # Round 4 performance front: resolved once, not once per candidate --
    # see is_within's own note.
    try:
        resolved_folder = folder.resolve()
    except (OSError, ValueError):
        resolved_folder = None
    found = []
    excluded = []
    for candidate in folder.rglob("*.md"):
        if not is_within(folder, candidate, resolved_base=resolved_folder):
            excluded.append(candidate)
            continue
        result = parse_any_filename(candidate.name, config)
        if result is not None:
            scheme, parsed = result
            found.append((scheme, parsed, candidate))
    if warnings is not None:
        warning = excluded_candidate_warning(excluded)
        if warning:
            warnings.append(warning)
        # Round 6 resilience re-run, Finding B, class closure: rglob
        # (used above) silently swallows an OSError from an unreadable
        # subdirectory -- see find_unreadable_subdirectories' own note.
        unreadable = find_unreadable_subdirectories(folder)
        if unreadable:
            names = ", ".join(unreadable)
            warnings.append(
                f"{len(unreadable)} subdirectory/subdirectories under {folder} could not be scanned "
                f"(permission denied or similar) -- this scan may be missing decision files inside them: {names}."
            )
    return found


def reject_folderadr_change_if_decisions_exist(old_folder, old_folderadr, new_folderadr, old_config, warnings=None):
    """Round 5 stability re-run, Finding 5: changing `folderadr` on a
    repository that already has recognized decisions makes every one of
    them invisible at its old, still-real path -- an orphaned-data risk
    no amount of "also create the new folder" can fix on its own, and a
    split-lock-scope race no test could reliably reproduce (two commands
    straddling the change would lock different directories, never
    excluding each other). Confirmed with the user: a folderadr change is
    only ever valid when the OLD folder has no recognized decisions yet --
    otherwise this raises a structured, mappable error instead of the
    silent data-loss/race the original finding described.

    Scans against `old_config` (never the new one): the existing files
    were written under the OLD naming rules, not the new ones.

    Round 6 resilience re-run, Finding B: unlike scan_decisions' other
    callers (a warning is enough there -- nothing unsafe happens from an
    under-reported inventory), this guard gates a real safety decision --
    `existing == []` here is only trustworthy if the scan that produced
    it was actually complete. Fails closed instead of allowing an
    orphaning it could not actually rule out."""
    if new_folderadr == old_folderadr:
        return
    unreadable = find_unreadable_subdirectories(old_folder)
    if unreadable:
        raise CommandError(
            "folderadr-change-scan-incomplete",
            f"Cannot safely determine whether '{old_folderadr}' still has decisions: "
            f"{len(unreadable)} subdirectory/subdirectories could not be scanned.",
            data={"folderadr": old_folderadr, "unreadable": unreadable},
            warnings=warnings,
        )
    existing = scan_decisions(old_folder, old_config, warnings=warnings)
    if existing:
        raise CommandError(
            "folderadr-change-blocked-by-existing-decisions",
            f"Cannot change folderadr from '{old_folderadr}' to '{new_folderadr}': "
            f"{len(existing)} existing decision(s) under '{old_folderadr}' would become invisible.",
            data={"folderadr": old_folderadr, "existing_decisions": len(existing)},
            warnings=warnings,
        )


def verify_folderadr_unchanged_since_lock(config_path, locked_folderadr, warnings=None):
    """Round 6 stability re-run, root cause shared by 8 call sites: the
    repository lock's own location is necessarily derived from a config
    read taken BEFORE the lock (a chicken-and-egg no different from
    init's own documented exemption -- you cannot look up where the lock
    lives without already knowing folderadr). If folderadr changes in
    the window between that read and the acquire, a command can lock,
    scan, and write against a directory the repository no longer uses at
    all. Reproduced live (round 6): an orphaned decision left under the
    stale path, and two processes locking two different directories with
    zero mutual exclusion between them -- the exact class ADR001 part 2
    (freshness) exists to close, just never applied to folderadr itself.

    Call this immediately after acquire_repo_lock returns, before doing
    anything else that depends on folderadr -- and use the config this
    returns from then on, not whatever was read before the lock: every
    other field could have drifted too, not just folderadr."""
    fresh_config = load_repo_config(config_path)
    if fresh_config.folderadr != locked_folderadr:
        raise CommandError(
            "folderadr-changed-after-lock-acquired",
            f"folderadr changed from '{locked_folderadr}' to '{fresh_config.folderadr}' while this call was "
            "acquiring the repository lock, so the lock's own location is no longer current -- no write was "
            "made. Retry.",
            data={"locked_folderadr": locked_folderadr, "current_folderadr": fresh_config.folderadr},
            warnings=warnings,
        )
    return fresh_config


def next_number(decisions):
    """Mirrors AdrService.GetNextNumberFrom: 1 if none exist, else max+1."""
    if not decisions:
        return 1
    return max(parsed.number for _, parsed, _ in decisions) + 1


def find_by_unique_title(title, config, decisions):
    """Mirrors AdrService.GetFileByUniqueTitleFrom. Returns the matching
    Path, or None."""
    key = unique_title_key(title, config)
    for _, parsed, path in decisions:
        if parsed.title is not None and unique_title_key(parsed.title, config) == key:
            return path
    return None


def find_repo_root(file_path):
    """Mirrors FileSystemService.GetFileRootRepositoryPath: walk up from
    the file's own directory looking for adr-config.adrplus. Returns the
    config file's Path, or None if never found."""
    directory = file_path.parent
    while True:
        candidate = directory / "adr-config.adrplus"
        if candidate.is_file():
            return candidate
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


_HEADER_READ_CHUNK_SIZE = 4096
_REAL_NEWLINE_BYTES = re.compile(rb"\r\n|\r|\n")


def _read_header_bytes(path, count):
    """Shared by read_header_lines/read_header_lines_with_report: reads
    only enough of `path` to recover the first `count` real lines (see
    split_real_lines) -- never the whole file. Reads in bounded chunks,
    growing only if the header genuinely doesn't fit in one (the config
    schema's own field-length limits keep a real header well under a
    single chunk in practice).

    Round 5 stability re-run, Finding 4: this read (and every other
    caller of this project's own documented Windows "pending delete"/
    sharing-violation contention window) had no PermissionError
    tolerance at all -- unlike the write side (atomic_write.py) and the
    lock-file read side (core/lock.py's own _read_lock), which both
    already retry it. Measured live at ~0.2% of reads under real
    concurrent writers. Shares core/io_retry.py's loop rather than being
    a third independent copy."""

    def _open_and_read():
        with open(path, "rb") as handle:
            buffer = handle.read(_HEADER_READ_CHUNK_SIZE)
            while len(_REAL_NEWLINE_BYTES.findall(buffer)) < count:
                more = handle.read(_HEADER_READ_CHUNK_SIZE)
                if not more:
                    break
                buffer += more
            return buffer

    return read_with_permission_retry(_open_and_read)


def read_header_lines(path, count=HEADER_LINE_COUNT):
    """Performance backlog item: reads only enough of `path` to recover
    the first `count` real lines -- never the whole file. Used wherever
    only the header is needed (family membership checks), which
    previously read a candidate's entire body, however large, just to
    look at its first 12 lines. Tolerates invalid bytes the same way
    read_lines does."""
    text = _read_header_bytes(path, count).decode("utf-8", errors="replace")
    return split_real_lines(text)[:count]


def read_header_lines_with_report(path, count=HEADER_LINE_COUNT):
    """Same bounded read as read_header_lines, but also reports whether
    whatever was actually read needed a lossy decode (round 4
    performance front, Finding D: a scan deciding only header-based
    eligibility -- migrate's own scan phase -- only needs to know about
    corruption within the header itself, since parse_header never looks
    past line `count`; a corrupted byte in the body is irrelevant to
    eligibility and passes through untouched in migrate's own write
    phase either way, which copies raw bytes verbatim). For a small
    file, the bounded read's own chunk boundary may still include some
    body content in what it decodes -- that's a harmless side effect of
    the chunk size, not a claim that corruption is ever checked
    per-line; only content genuinely beyond the read is never seen."""
    buffer = _read_header_bytes(path, count)
    try:
        text = buffer.decode("utf-8")
        encoding_repaired = False
    except UnicodeDecodeError:
        text = buffer.decode("utf-8", errors="replace")
        encoding_repaired = True
    return split_real_lines(text)[:count], encoding_repaired


def read_lines_with_report(path):
    """Same as read_lines, but also reports whether the decode was lossy
    (observability audit: invalid UTF-8 bytes get silently replaced with
    U+FFFD -- permanently, the instant the file is next rewritten -- with
    nothing telling the caller this happened).

    Round 5 stability re-run, Finding 4: same transient-PermissionError
    tolerance as _read_header_bytes' own note -- this is read_target's
    own primary read on every per-file command."""
    raw_bytes = read_with_permission_retry(path.read_bytes)
    try:
        text = raw_bytes.decode("utf-8")
        encoding_repaired = False
    except UnicodeDecodeError:
        text = raw_bytes.decode("utf-8", errors="replace")
        encoding_repaired = True
    return split_real_lines(text), encoding_repaired


def read_body(lines):
    """Mirrors AdrService.cs:413-417: rejoin everything past the 12-line
    header with THIS host's line separator (discarding whatever per-line
    terminator the source had), plus exactly one trailing terminator when
    there is any body content at all."""
    body_lines = lines[HEADER_LINE_COUNT:]
    if not body_lines:
        return ""
    return os.linesep.join(body_lines) + os.linesep


def resolve_repo_and_target(fileadr):
    """The non-content-dependent half of load_target (round 4 ADR001,
    doc/adr/ADR001V01-...): resolve the extension default, find the
    file's own repository root by walking up for adr-config.adrplus, and
    load+validate that config -- everything that doesn't require reading
    the target file's own content. Split out so a caller that goes on to
    write can acquire the repository lock (scoped to config.folderadr,
    only resolvable once `config` is known) BEFORE the content-dependent
    read (read_target below), keeping that read fresh with respect to the
    lock instead of captured before it."""
    fileadr = Path(fileadr)
    if fileadr.suffix == "":
        fileadr = fileadr.with_suffix(".md")
    if not fileadr.is_file():
        raise CommandError("file-not-found", f"File not found: {fileadr}")

    config_path = find_repo_root(fileadr)
    if config_path is None:
        raise CommandError(
            "cannot-determine-root-path", f"Cannot determine the repository root for: {fileadr}"
        )
    config = load_repo_config(config_path)
    return config, config_path.parent, fileadr


def read_target(path, config):
    """The content-dependent half of load_target (round 4 ADR001): reads
    and parses the target file's own name and header. Call this AFTER
    acquiring the repository lock for any command that goes on to write,
    so eligibility/write decisions are made from a fresh read, not one
    captured before the lock -- the reproduced defect (round 4, stability
    Finding 2) ADR001 closes."""
    lines, encoding_repaired = read_lines_with_report(path)
    found = parse_any_filename(path.name, config)
    if found is None:
        raise CommandError("filename-not-recognized", f"Filename matches no naming scheme: {path.name}")
    _, filename_info = found

    header = parse_header(lines, config)
    if not header.is_valid:
        # Usability audit A4: header.error is already the specific,
        # correctly-computed reason (adr-file-empty, adr-header-title-
        # not-found, status-line-date-invalid, ...) -- use it as the code
        # itself instead of discarding it behind one fixed label.
        raise CommandError(header.error or "header-invalid", "Header is not structurally valid.")

    return filename_info, header, lines, encoding_repaired


def load_target(fileadr):
    """Ported from the common preamble approve/reject/undo/supersede/
    version/revise all share: resolve the extension default, find the
    file's own repository root by walking up for adr-config.adrplus, load
    +validate that config, then parse this file's own name and header.
    Declares (Fase 6 checklist): recognizes BOTH naming schemes.

    Kept as a single call for any caller that doesn't need the lock-then-
    read split (round 4 ADR001) -- see resolve_repo_and_target/
    read_target above for that split, now used by every command that
    goes on to write."""
    config, root, path = resolve_repo_and_target(fileadr)
    filename_info, header, lines, encoding_repaired = read_target(path, config)
    return config, root, path, filename_info, header, lines, encoding_repaired


def family_members(folder, config, number, warnings=None):
    """Every decision (current or legacy scheme) sharing `number` that
    actually counts as a family member, with its parsed header attached --
    mirrors AdrService.ReadAllAdrByNumber, which filters on
    `aux.Header.IsValid || aux.Header.IsMigrated` (counts_as_family_member)
    before ever including a scanned file. Legacy-scheme census audit: a
    hand-written legacy file matched by FILENAME but never run through
    `migrate` has no valid header at all -- without this filter it still
    got counted, and has_pending_sibling/latest_in_family (below) would
    misjudge it as a genuine pending/latest member.

    `warnings`, when given, is forwarded to scan_decisions -- see its own
    note (round 4 observability audit, Finding 3)."""
    members = []
    for _, parsed, path in scan_decisions(folder, config, warnings=warnings):
        if parsed.number != number:
            continue
        # Performance backlog item: only the header (12 lines) decides
        # membership -- read_header_lines never loads the (potentially
        # large) body just to check that.
        header = parse_header(read_header_lines(path), config)
        if not counts_as_family_member(header):
            continue
        members.append((parsed, header, path))
    return members


def has_superseded_sibling(folder, config, number, members=None):
    """Performance backlog item: accepts an already-fetched `members` list
    (from family_members) so a caller needing more than one of
    has_superseded_sibling/has_pending_sibling/latest_in_family can scan
    the directory once and reuse the same snapshot, instead of each
    function independently re-scanning (undo did 2 scans, version/revise
    did 3, for a single command invocation)."""
    if members is None:
        members = family_members(folder, config, number)
    return any(header.status_change == "Superseded" for _, header, _ in members)


def has_pending_sibling(folder, config, number, members=None):
    """Mirrors the undo-specific extra check: a family member that is
    itself still unresolved (no update status) and NOT a migrated
    placeholder blocks undo -- undoing would otherwise leave two
    simultaneously-pending members of the same family. See
    has_superseded_sibling's own note about the optional `members`."""
    if members is None:
        members = family_members(folder, config, number)
    return any(header.status_update is None and not header.is_migrated for _, header, _ in members)


def latest_in_family(folder, config, number, members=None):
    """Mirrors AdrService.GetLatestADRSequence: the family member with the
    highest (version, revision), same tie-break as ReadAllAdr's sort.
    Returns (ParsedFileName, HeaderParseResult, Path), or None. See
    has_superseded_sibling's own note about the optional `members`."""
    if members is None:
        members = family_members(folder, config, number)
    if not members:
        return None
    return max(members, key=lambda item: (item[0].version, item[0].revision or 0))


def ineligibility_reason_for_approve_or_reject(header):
    """Mirrors ApproveCommandHandler/RejectCommandHandler's
    SelectionCondition -- identical in both, and confirmed against the
    real ApproveCommandHandler.cs:59 (`StatusUpdate == AdrStatus.Unknown`):
    eligible requires status_update to be None, full stop -- not merely
    "not Accepted and not Rejected". Returns None when eligible, else the
    SPECIFIC reason (usability audit: a single collapsed
    not-eligible-for-* code couldn't distinguish "already Accepted" from
    "already Rejected" from "already Superseded" -- each calls for a
    different recovery action). Callers already guarantee header.is_valid
    via load_target before reaching this check.

    Audit round 2 regression fix: a structurally-valid but corrupted/hand-
    edited status_update (e.g. the "Changed" cell holding the "Proposed"
    or "Superseded" label text) used to fall through to eligible here --
    confirmed reachable live via approve on such a file. Any non-None,
    non-Accepted, non-Rejected value must be ineligible too."""
    if not (header.status_create == "Proposed" or (header.status_create is None and header.is_migrated)):
        return "not-proposed"
    if header.status_change is not None:
        return "already-superseded"
    if header.status_update is None:
        return None
    if header.status_update == "Accepted":
        return "already-accepted"
    if header.status_update == "Rejected":
        return "already-rejected"
    return "unexpected-status"


def ineligibility_reason_for_undo(header):
    """Mirrors UndoStatusCommandHandler's SelectionCondition. See
    ineligibility_reason_for_approve_or_reject's own note."""
    if not (header.status_create == "Proposed" or (header.status_create is None and header.is_migrated)):
        return "not-proposed"
    if header.status_change is not None:
        return "already-superseded"
    if header.status_update is None:
        return "still-proposed"
    return None


def ineligibility_reason_for_supersede(header):
    """Mirrors SupersedeCommandHandler's SelectionCondition: must already
    be Accepted (or a migrated placeholder with no update status yet).
    See ineligibility_reason_for_approve_or_reject's own note.

    Audit round 2 fix: the boolean outcome here always matched the
    original (ineligible either way), but a corrupted status_update (e.g.
    "Superseded" landing in the wrong cell) was mislabeled "already-
    rejected" -- distinguished from a genuine Rejected value now."""
    if not (header.status_create == "Proposed" or (header.status_create is None and header.is_migrated)):
        return "not-proposed"
    if header.status_change is not None:
        return "already-superseded"
    if header.status_update == "Accepted" or (header.status_update is None and header.is_migrated):
        return None
    if header.status_update is None:
        return "still-proposed"
    if header.status_update == "Rejected":
        return "already-rejected"
    return "unexpected-status"


def ineligibility_reason_for_version_or_revise(header):
    """Mirrors Version/ReviseCommandHandler's SelectionCondition (identical
    in both): must already be Accepted OR Rejected (or a migrated
    placeholder with no update status yet). See
    ineligibility_reason_for_approve_or_reject's own note.

    Audit round 2 fix: same mislabel class as ineligibility_reason_for_
    supersede -- a corrupted non-None, non-Accepted, non-Rejected value
    was labeled "still-proposed", which is only accurate when
    status_update genuinely is None."""
    if not (header.status_create == "Proposed" or (header.status_create is None and header.is_migrated)):
        return "not-proposed"
    if header.status_change is not None:
        return "already-superseded"
    if header.status_update in ("Accepted", "Rejected") or (header.status_update is None and header.is_migrated):
        return None
    if header.status_update is None:
        return "still-proposed"
    return "unexpected-status"


def _record_from_header(config, filename_info, header):
    """Mirrors Helper.CreateAdrRecord: rebuilds an AdrRecord-equivalent
    from an already-parsed header, ready for a targeted field mutation.
    Version/Revision come from the header AS READ, never recalculated;
    Revision is forced None whenever lenrevision == 0."""
    return DecisionRecord(
        number=filename_info.number,
        title=header.title,
        version=header.version or 0,
        revision=None if config.lenrevision == 0 else header.revision,
        scope=header.scope,
        domain=header.domain,
        status_create=header.status_create,
        date_create=header.date_create,
        status_update=header.status_update,
        date_update=header.date_update,
        status_change=header.status_change,
        date_change=header.date_change,
        superseded_by_file=header.superseded_by_file,
    )


def rewrite_status_field(path, config, lines, header, filename_info, *, field, status, refdate):
    """Mirrors StatusUpdateAdrAsync (`field="update"`) and
    StatusChangeAdrAsync (`field="change"`): mutate exactly one status+date
    pair on the already-parsed header, rebuild via build_header preserving
    every other field and the original body verbatim, and write the file.
    Returns the write's own attempt count too (observability audit) --
    callers can surface it as a warning when it's more than 1."""
    record = _record_from_header(config, filename_info, header)
    setattr(record, f"status_{field}", status)
    setattr(record, f"date_{field}", refdate if status is not None else None)

    content = build_header(config, record, migrated=header.is_migrated) + read_body(lines)
    attempts = atomic_write_text(path, content)
    return record, content, attempts


def mark_superseded(path, config, lines, header, filename_info, successor_number, refdate):
    """Mirrors StatusChangeSupersedeAdrAsync: like rewrite_status_field's
    "change" field, but also stamps the successor's own zero-padded
    sequence number into the Superseded row. NOT a filename, despite
    DecisionRecord's `superseded_by_file` name (kept as-is -- it mirrors
    GetHeader's own `supersedefile` parameter/row): confirmed in
    SupersedeCommandHandler.cs, the real value passed is
    `nextNumber.ToString($"D{LenSeq}")`, a bare padded number."""
    record = _record_from_header(config, filename_info, header)
    record.status_change = "Superseded"
    record.date_change = refdate
    record.superseded_by_file = f"{successor_number:0{config.lenseq}d}"

    content = build_header(config, record, migrated=header.is_migrated) + read_body(lines)
    attempts = atomic_write_text(path, content)
    return record, content, attempts
