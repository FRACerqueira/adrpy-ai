"""Shared lifecycle-transition helpers: date-reference validation,
title-uniqueness/next-number resolution, and the read-mutate-rewrite
mechanics every status-transition command
(approve/reject/undo/supersede/version/revise) shares -- one function per
concern, not copies."""

import codecs
import re
from dataclasses import replace as replace_fields
from datetime import date as date_cls
from pathlib import Path

from adrpy.core.atomic_write import (
    LINESEP_BYTES,
    STREAM_CHUNK_SIZE,
    atomic_write_chunks,
    atomic_write_text,
    join_lines_with_trailing_terminator,
    split_real_lines,
)
from adrpy.core.casing import unique_title_key
from adrpy.core.config import _STATUS_LABEL_FIELDS, load_repo_config
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import HEADER_LINE_COUNT, DecisionRecord, build_header, parse_header
from adrpy.core.io_retry import read_with_permission_retry
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import find_unreadable_subdirectories, is_within, resolve_within
from adrpy.core.warnings import excluded_candidate_warning, ignored_file_warning, marker_label_mismatch_warning


def parse_refdate(text):
    """Shared `--refdate` parsing: defaults to today when omitted, else
    strict ISO (YYYY-MM-DD)."""
    if not text:
        return date_cls.today()
    try:
        return date_cls.fromisoformat(text)
    except ValueError as error:
        raise CommandError(FailureCodes.REFDATE_INVALID_FORMAT, f"Invalid date: {text}") from error


def validate_refdate_not_in_future(refdate):
    if refdate > date_cls.today():
        raise CommandError(FailureCodes.REFDATE_IN_FUTURE, f"Reference date {refdate.isoformat()} is in the future.")


def validate_refdate_not_before(refdate, not_before):
    if refdate < not_before:
        raise CommandError(
            FailureCodes.REFDATE_BEFORE_HISTORY,
            f"Reference date {refdate.isoformat()} is before {not_before.isoformat()}.",
        )


def scan_decisions(folder, config, warnings=None, *, strict=False, incomplete_code=None):
    """Recognizes BOTH naming schemes -- every command that resolves
    "next number" or "does this title already exist" must consider
    legacy files too. Returns a list of (scheme, ParsedFileName,
    path) for every recognized file under `folder`.

    When `warnings` is given, reports any candidate is_within excluded
    because its real path escapes `folder`'s boundary -- otherwise
    silent, indistinguishable from "no such file" to every caller.

    `strict=True` (with a caller-supplied `incomplete_code`) fails closed
    instead of merely warning when an unreadable subdirectory makes this
    scan untrustworthy -- warning alone lets a hidden family member (in
    an unreadable subdirectory) silently defeat `family_members`'s own
    safety guards and `next_number`'s allocation, reproducing a "two live
    successors" corruption with no concurrency needed at all. Callers feeding a real safety
    decision from this result (family membership, next-number
    allocation, title uniqueness) must opt into `strict`; callers only
    reporting (explore, a generic listing) keep the existing warn-only
    behavior -- nothing unsafe happens from an under-reported inventory
    there."""
    if not folder.is_dir():
        return []
    # Resolved once, not once per candidate -- see is_within's own note.
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
    # rglob (used above) silently swallows an OSError from an unreadable
    # subdirectory -- see find_unreadable_subdirectories' own note. Only
    # computed when actually needed (strict, or warnings collected).
    unreadable = find_unreadable_subdirectories(folder) if (strict or warnings is not None) else []
    if unreadable and strict:
        raise CommandError(
            incomplete_code,
            f"Cannot safely scan {folder}: {len(unreadable)} subdirectory/subdirectories could not be "
            "scanned (permission denied or similar).",
            data={"folder": str(folder), "unreadable": unreadable},
            warnings=warnings,
        )
    if warnings is not None:
        warning = excluded_candidate_warning(excluded)
        if warning:
            warnings.append(warning)
        if unreadable:
            names = ", ".join(unreadable)
            warnings.append(
                f"{len(unreadable)} subdirectory/subdirectories under {folder} could not be scanned "
                f"(permission denied or similar) -- this scan may be missing decision files inside them: {names}."
            )
    return found


def reject_folderadr_change_if_decisions_exist(
    old_folder, old_folderadr, new_folderadr, old_config, *, target, new_config, warnings=None
):
    """Changing `folderadr` on a repository that already has recognized
    decisions makes every one of them invisible at its old, still-real
    path -- an orphaned-data risk no amount of "also create the new
    folder" can fix on its own, and a split-lock-scope race no test could
    reliably reproduce (two commands straddling the change would lock
    different directories, never excluding each other). A folderadr
    change is only ever valid when the OLD folder has no recognized
    decisions yet -- otherwise this raises a structured, mappable error
    instead of silent data loss/a race.

    Scans against `old_config` (never the new one): the existing files
    were written under the OLD naming rules, not the new ones.

    Unlike scan_decisions' other callers (a warning is enough there --
    nothing unsafe happens from an under-reported inventory), this guard
    gates a real safety decision --
    `existing == []` here is only trustworthy if the scan that produced
    it was actually complete. Fails closed instead of allowing an
    orphaning it could not actually rule out.

    Also guards the opposite direction (confirmed live): `new_folderadr`
    may already point at a directory
    holding unrelated pre-existing content. Any of it that would be newly
    recognized as a decision under `new_config` -- the rules that govern
    every future scan of that directory -- gets silently adopted with no
    warning at all, corrupting next-number allocation (confirmed live: a
    single unrelated file matching the naming scheme made the next `new`
    allocate ADR008V01 instead of ADR001V01). Same shape hazard as
    --separator's own adoption-check (ADR004V02), just triggered by a
    folder move instead of a naming-rule change. Skipped entirely when
    the new folder does not exist yet -- the overwhelmingly common case,
    and `find_unreadable_subdirectories` treats a missing path as
    unreadable, which would otherwise block it."""
    if new_folderadr == old_folderadr:
        return
    unreadable = find_unreadable_subdirectories(old_folder)
    if unreadable:
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGE_SCAN_INCOMPLETE,
            f"Cannot safely determine whether '{old_folderadr}' still has decisions: "
            f"{len(unreadable)} subdirectory/subdirectories could not be scanned.",
            data={"folderadr": old_folderadr, "unreadable": unreadable},
            warnings=warnings,
        )
    existing = scan_decisions(old_folder, old_config, warnings=warnings)
    if existing:
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS,
            f"Cannot change folderadr from '{old_folderadr}' to '{new_folderadr}': "
            f"{len(existing)} existing decision(s) under '{old_folderadr}' would become invisible.",
            data={"folderadr": old_folderadr, "existing_decisions": len(existing)},
            warnings=warnings,
        )

    new_folder = resolve_within(target, new_folderadr)
    if new_folder.is_dir():
        new_unreadable = find_unreadable_subdirectories(new_folder)
        if new_unreadable:
            raise CommandError(
                FailureCodes.FOLDERADR_CHANGE_SCAN_INCOMPLETE,
                f"Cannot safely determine whether '{new_folderadr}' already has unrelated content: "
                f"{len(new_unreadable)} subdirectory/subdirectories could not be scanned.",
                data={"folderadr": new_folderadr, "unreadable": new_unreadable},
                warnings=warnings,
            )
        adopted = sorted((str(path) for _, _, path in scan_decisions(new_folder, new_config, warnings=warnings)))
        if adopted:
            raise CommandError(
                FailureCodes.FOLDERADR_CHANGE_WOULD_ADOPT_UNRELATED_FILES,
                f"Cannot change folderadr to '{new_folderadr}': {len(adopted)} file(s) already there would "
                "silently become recognized decisions.",
                data={"folderadr": new_folderadr, "adopted_files": adopted},
                warnings=warnings,
            )


# ADR004V02: two groups, not one flat list -- `migrationpattern` only
# affects recognition of LEGACY-scheme files (naming.py's
# parse_legacy_filename is its only reader); every other guarded field
# is blanket (blocks on any recognized decision, any scheme).
#
# `separator` looks like it should be current-scheme-scoped the same
# way (naming.py's parse_filename, the CURRENT scheme, is its only
# direct reader) -- an earlier version of this fix scoped it that way,
# and that was wrong: parse_any_filename tries the CURRENT scheme
# FIRST, falling back to legacy only if it doesn't match. A separator
# value that happens to already appear in a legacy-scheme filename can
# make parse_filename newly match a file that previously only matched
# parse_legacy_filename -- silently RECLASSIFYING a legacy decision as
# current-scheme, under a different number/title, with zero warning.
# Confirmed live: a legacy-only repository's `separator` change was
# incorrectly ALLOWED by the scoped version, and the file's own scheme
# flipped on the next scan. `migrationpattern` has no mirror risk --
# parse_filename never reads it, so a current-scheme file can never be
# reclassified legacy by a migrationpattern change, confirmed by
# reading naming.py directly. `separator` is blanket again as a result;
# only `migrationpattern` is genuinely safe to scope.
_STATUS_LABEL_GUARD_FIELDS = _STATUS_LABEL_FIELDS
_BLANKET_GUARD_FIELDS = _STATUS_LABEL_GUARD_FIELDS + ("separator",)
# `migrationpattern` is only ever read by naming.py's
# parse_legacy_filename (the LEGACY scheme) -- parse_filename never
# references it, and (unlike separator) there is no reverse
# reclassification risk (see the note above). ADR004V01 originally
# dismissed this field on a write-dependency argument ("not a value
# this tool's own writes depend on staying stable") that never
# addressed its READ/recognition dependency -- confirmed live and in
# naming.py's own source; corrected in ADR004V02.
_LEGACY_SCHEME_GUARD_FIELDS = ("migrationpattern",)


def reject_status_or_separator_change_if_decisions_exist(old_folder, old_config, new_config, warnings=None):
    """ADR004V01/V02: a status label, `separator`, or `migrationpattern`
    change on a repository that already has recognized decisions can
    make some or all of them unrecognized -- confirmed live for status
    labels and `separator` (a changed statusnew/statusacc/statusrej/
    statussup label stops core/header.py's own label-text match from
    recognizing an existing, marker-less status cell; a changed
    separator can stop core/naming.py's own current-scheme filename
    parse from recognizing an existing file at all, OR silently
    reclassify a legacy-scheme file as current-scheme -- see the note
    on _BLANKET_GUARD_FIELDS above for why `separator` is blanket, not
    scoped, despite only being read by one scheme's own parser), and by
    direct code reading for `migrationpattern` (core/naming.py's own
    parse_legacy_filename re-derives every legacy-scheme file's number/
    version/revision/prefix by POSITION and LENGTH from
    `config.migrationpattern`, read fresh on every call -- nothing
    stored in the file itself pins its own identity).

    `migrationpattern` blocks only if a LEGACY-scheme decision exists;
    every other guarded field blocks on ANY recognized decision, any
    scheme. Still unconditional WITHIN the scheme(s) it actually
    affects -- unlike the ADR004V01 marker itself, this does not check
    whether a given file is already marker-protected against a
    status-label change specifically (no marker-based equivalent exists
    for `separator`/`migrationpattern` at all). Same blanket-within-
    scope shape reject_folderadr_change_if_decisions_exist above
    already uses, not a per-file analysis.

    Scans against `old_config` (never `new_config`): the existing files
    were written/named under the OLD rules, not the new ones -- same
    reasoning as reject_folderadr_change_if_decisions_exist.

    The scan-incomplete fail-closed check below is NOT scheme-scoped --
    an unreadable subdirectory's own contents (and therefore scheme) are
    unknowable, so any guarded field change fails closed regardless of
    which scheme it would otherwise only need to protect. `existing_
    decisions` in the blocked-error's own data is scoped to exactly what
    the blocking field(s) actually affect: every recognized decision
    (any scheme) when a blanket field is blocking, or only the legacy-
    scheme subset when migrationpattern is the sole blocking field --
    never an inflated total that includes decisions the blocking
    field(s) have no bearing on.

    A second, independent check (ADR004V0x): every check above is keyed
    on decisions already recognized under `old_config` -- none of them
    catch the opposite direction, a file NOT currently recognized by
    either scheme becoming newly recognized. Confirmed live: an
    unrelated, hand-written file with no relationship to the decision
    lifecycle could otherwise be silently adopted as a genuine decision
    the moment `separator` changes to a value its own name happens to
    contain, corrupting next-number allocation and title-uniqueness for
    every decision created afterward, with zero warning. Scoped to
    `separator` only -- `migrationpattern` deliberately keeps its
    existing "may newly recognize pre-existing legacy files" behavior,
    since that is its own documented, intentional purpose (ADR002V01),
    not an accident."""
    blanket_fields_changed = [
        field for field in _BLANKET_GUARD_FIELDS if getattr(old_config, field) != getattr(new_config, field)
    ]
    legacy_scheme_fields_changed = [
        field for field in _LEGACY_SCHEME_GUARD_FIELDS if getattr(old_config, field) != getattr(new_config, field)
    ]
    changed_fields = blanket_fields_changed + legacy_scheme_fields_changed
    if not changed_fields:
        return

    unreadable = find_unreadable_subdirectories(old_folder)
    if unreadable:
        raise CommandError(
            FailureCodes.STATUS_OR_SEPARATOR_CHANGE_SCAN_INCOMPLETE,
            f"Cannot safely determine whether existing decisions would be affected by changing "
            f"{', '.join(changed_fields)}: {len(unreadable)} subdirectory/subdirectories could not be "
            "scanned.",
            data={"changed_fields": changed_fields, "unreadable": unreadable},
            warnings=warnings,
        )

    existing = scan_decisions(old_folder, old_config, warnings=warnings)
    legacy_existing_count = sum(1 for scheme, _, _ in existing if scheme == "legacy")

    blocking_fields = []
    if blanket_fields_changed and existing:
        blocking_fields += blanket_fields_changed
    if legacy_scheme_fields_changed and legacy_existing_count:
        blocking_fields += legacy_scheme_fields_changed

    if blocking_fields:
        # A blanket field blocking means every recognized decision (any
        # scheme) is genuinely at risk -- len(existing) is correct even
        # when migrationpattern is ALSO blocking, since that set is
        # always a subset. Only when migrationpattern is the SOLE
        # blocking field does the narrower legacy-only count apply.
        affected_count = len(existing) if blanket_fields_changed and existing else legacy_existing_count
        raise CommandError(
            FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS,
            f"Cannot change {', '.join(blocking_fields)}: {affected_count} existing decision(s) would no "
            "longer be recognized.",
            data={"changed_fields": blocking_fields, "existing_decisions": affected_count},
            warnings=warnings,
        )

    # Every check above is keyed on decisions already recognized under
    # OLD_config -- none of them catch the opposite direction, a file
    # NOT currently recognized (by either scheme) becoming newly
    # recognized. `separator` has no legitimate reason to ever do this
    # (unlike `migrationpattern`, whose whole documented purpose IS to
    # newly recognize pre-existing legacy files -- see ADR002V01 -- so
    # this check is deliberately NOT applied to it). Reuses `existing`
    # (already scanned, no need to rescan with old_config again) -- only
    # one more scan is needed.
    #
    # Scans with a config that has ONLY separator changed, every other
    # field (migrationpattern in particular) still at its OLD value --
    # NOT the full `new_config`: the full-new_config version cross-
    # attributes -- parse_filename reads only separator,
    # parse_legacy_filename reads only migrationpattern (naming.py), so
    # scanning with new_config's migrationpattern too would also pick up
    # files ONLY newly recognized because of that field's own,
    # separately-evaluated, intentionally-allowed adoption -- and blame
    # the block on separator, wrongly refusing a call that changes both
    # fields at once even when separator itself adopts nothing at all
    # (confirmed live).
    if "separator" in blanket_fields_changed:
        old_recognized_paths = {path for _, _, path in existing}
        separator_only_config = replace_fields(old_config, separator=new_config.separator)
        adopted = sorted(
            (
                path
                for _, _, path in scan_decisions(old_folder, separator_only_config)
                if path not in old_recognized_paths
            ),
            key=str,
        )
        if adopted:
            raise CommandError(
                FailureCodes.SEPARATOR_CHANGE_WOULD_ADOPT_UNRELATED_FILES,
                f"Cannot change separator: {len(adopted)} file(s) not currently recognized as a decision "
                "would silently become one.",
                data={"adopted_files": [str(path) for path in adopted]},
                warnings=warnings,
            )


def verify_folderadr_unchanged_since_lock(config_path, locked_folderadr, warnings=None):
    """The repository lock's own location is necessarily derived from a
    config read taken BEFORE the lock (a chicken-and-egg no different
    from init's own documented exemption -- you cannot look up where the
    lock lives without already knowing folderadr). If folderadr changes
    in the window between that read and the acquire, a command can lock,
    scan, and write against a directory the repository no longer uses at
    all -- reproduced live: an orphaned decision left under the stale
    path, and two processes locking two different directories with zero
    mutual exclusion between them. The exact class ADR001 part 2
    (freshness) exists to close, just never applied to folderadr itself.

    Call this immediately after acquire_repo_lock returns, before doing
    anything else that depends on folderadr -- and use the config this
    returns from then on, not whatever was read before the lock: every
    other field could have drifted too, not just folderadr."""
    fresh_config = load_repo_config(config_path)
    if fresh_config.folderadr != locked_folderadr:
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGED_AFTER_LOCK_ACQUIRED,
            f"folderadr changed from '{locked_folderadr}' to '{fresh_config.folderadr}' while this call was "
            "acquiring the repository lock, so the lock's own location is no longer current -- no write was "
            "made. Retry.",
            data={"locked_folderadr": locked_folderadr, "current_folderadr": fresh_config.folderadr},
            warnings=warnings,
        )
    return fresh_config


def next_number(decisions):
    """1 if none exist, else max+1."""
    if not decisions:
        return 1
    return max(parsed.number for _, parsed, _ in decisions) + 1


def find_by_unique_title(title, config, decisions):
    """Returns the matching Path, or None."""
    key = unique_title_key(title, config)
    for _, parsed, path in decisions:
        if parsed.title is not None and unique_title_key(parsed.title, config) == key:
            return path
    return None


def find_repo_root(file_path):
    """Walks up from the file's own directory looking for
    adr-config.adrplus. Returns the config file's Path, or None if never
    found."""
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
# Without this cap, the read loop would continue to EOF whenever a
# pathological/corrupted file never accumulates `count` real newlines --
# a single-chunk-per-iteration bound would still let such a file be read
# in full, just one chunk at a time. 4 chunks (16KB) is generous relative
# to a genuine header (a few KB at most, per the config schema's own
# field-length limits) -- a file that still doesn't have `count` real
# newlines within this cap is treated as too-short/malformed by
# parse_header's own existing check, never read further.
_HEADER_READ_MAX_BYTES = _HEADER_READ_CHUNK_SIZE * 4
_REAL_NEWLINE_BYTES = re.compile(rb"\r\n|\r|\n")


def _read_header_bytes(path, count):
    """Shared by read_header_lines/read_header_lines_with_report: reads
    only enough of `path` to recover the first `count` real lines (see
    split_real_lines) -- never the whole file, and never past
    `_HEADER_READ_MAX_BYTES` even if `count` real newlines never appear.
    Reads in bounded chunks, growing only if the header genuinely
    doesn't fit in one (the config schema's own field-length limits keep
    a real header well under a single chunk in practice).

    Re-scans the whole accumulated buffer (never just the newest chunk in
    isolation) on every iteration: counting newlines within each
    freshly-read chunk ALONE double-counts a `\r\n` pair that straddles
    exactly on a chunk boundary (the `\r` as one chunk's own last byte,
    matched as a lone CR by that chunk's own isolated scan; the `\n` as
    the next chunk's own first byte, matched again as a lone LF by ITS
    isolated scan), which can make the loop believe it already found
    `count` real newlines one chunk-read too early, silently truncating
    the returned buffer before the file's true `count`-th line is ever
    read. Re-scanning the whole buffer each time lets the regex see both
    halves of a straddling CRLF together, correctly counted as one
    match. The buffer is still hard-capped at `_HEADER_READ_MAX_BYTES`
    (16KB), so a rescan is at most ~4 passes over at most 16KB each --
    O(1) relative to the file's own total size, never an unbounded-file
    quadratic blowup.

    This read tolerates a transient PermissionError, the same contention
    window the write side (atomic_write.py) and the lock-file read side
    (core/lock.py's own _read_lock) already retry -- measured live at
    ~0.2% of reads under real concurrent writers. Shares
    core/io_retry.py's loop rather than being a third independent copy."""

    def _open_and_read():
        with open(path, "rb") as handle:
            chunks = []
            total_bytes = 0
            newline_count = 0
            while newline_count < count and total_bytes < _HEADER_READ_MAX_BYTES:
                more = handle.read(_HEADER_READ_CHUNK_SIZE)
                if not more:
                    break
                chunks.append(more)
                total_bytes += len(more)
                newline_count = len(_REAL_NEWLINE_BYTES.findall(b"".join(chunks)))
            return b"".join(chunks)

    return read_with_permission_retry(_open_and_read)


def _without_leading_boms(text):
    """The tool never writes a BOM, so any run of them at the very start
    was added by an editor (or PowerShell 5.1's -Encoding UTF8) and is not
    content -- left in, it hides the header's first line."""
    return text.lstrip("\ufeff")


def read_header_lines(path, count=HEADER_LINE_COUNT):
    """Reads only enough of `path` to recover the first `count` real
    lines -- never the whole file. Used wherever only the header is
    needed (family membership checks): reading a candidate's entire
    body, however large, just to look at its first 12 lines would be
    wasteful. Tolerates invalid bytes the same way read_lines does."""
    text = _read_header_bytes(path, count).decode("utf-8", errors="replace")
    return split_real_lines(_without_leading_boms(text))[:count]


def read_header_lines_with_report(path, count=HEADER_LINE_COUNT):
    """Same bounded read as read_header_lines, but also reports whether
    whatever was actually read needed a lossy decode. A scan deciding
    only header-based eligibility -- migrate's own scan phase -- only
    needs to know about corruption within the header itself, since
    parse_header never looks past line `count`; a corrupted byte in the
    body is irrelevant to
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
    return split_real_lines(_without_leading_boms(text))[:count], encoding_repaired


def read_lines_with_report(path):
    """Same as read_lines, but also reports whether the decode was lossy
    -- invalid UTF-8 bytes get silently replaced with U+FFFD permanently,
    the instant the file is next rewritten, with nothing telling the
    caller this happened otherwise.

    Same transient-PermissionError tolerance as _read_header_bytes' own
    note -- this is read_target's own primary read on every per-file
    command."""
    raw_bytes = read_with_permission_retry(path.read_bytes)
    try:
        text = raw_bytes.decode("utf-8")
        encoding_repaired = False
    except UnicodeDecodeError:
        text = raw_bytes.decode("utf-8", errors="replace")
        encoding_repaired = True
    return split_real_lines(_without_leading_boms(text)), encoding_repaired


def read_body(lines):
    """Rejoins everything past the 12-line header with THIS host's line
    separator (discarding whatever per-line terminator the source had),
    plus exactly one trailing terminator when there is any body content
    at all."""
    return join_lines_with_trailing_terminator(lines[HEADER_LINE_COUNT:])


def _body_start_offset(header_buffer, count):
    """The exact byte offset in the ORIGINAL FILE where the body begins
    -- the end of the `count`-th real line terminator within
    `header_buffer` (a byte-exact prefix of that file, from
    _read_header_bytes). None if `header_buffer` doesn't contain that
    many real terminators (the file is too-short/malformed -- the same
    condition parse_header's own existing check already handles; no new
    handling needed here)."""
    matches = list(_REAL_NEWLINE_BYTES.finditer(header_buffer))
    if len(matches) < count:
        return None
    return matches[count - 1].end()


_BODY_DECODE_ERROR_HANDLER_NAME = "adrpy-body-stream-replace"


def stream_normalized_body_chunks(source_path, report):
    """Streams `source_path`'s own BODY (everything past its 12-line
    header), reproducing `read_body(read_lines_with_report(source_path))`'s
    historical output byte-for-byte (ADR006V01) -- every real line
    terminator converted to this host's os.linesep, invalid UTF-8 bytes
    replaced with U+FFFD, exactly one trailing terminator ensured for a
    non-empty body -- without ever holding the whole body in memory. The
    header itself is located via the already-bounded _read_header_bytes
    (schema-bounded, a few KB at most); only the body, which has no such
    bound, is read in fixed-size chunks.

    `report` is a caller-provided dict that receives
    `report["encoding_repaired"]` once this generator is fully exhausted
    -- meaningless to read before then (e.g. check it only after
    atomic_write_chunks, which fully consumes its chunk factory, returns).

    Newline normalization runs at the BYTE level, before UTF-8 decoding:
    a real terminator byte (0x0D/0x0A) can never appear as part of a
    valid multi-byte UTF-8 continuation byte (0x80-0xBF), so this is safe
    regardless of, and independent from, the encoding-repair step that
    follows it. A lone `\\r` as the very last byte of a chunk is held
    back (not yet convertible -- the next chunk's first byte could still
    complete a `\\r\\n` pair) rather than converted immediately.

    Not reentrant across concurrent calls within the same process (the
    error-handler name is re-registered, closing over THIS call's own
    `report`, immediately before use) -- safe for this project's own
    single-threaded-per-command-invocation model; never call this a
    second time before the first call's generator has been fully
    consumed."""
    report["encoding_repaired"] = False

    def _replace_and_flag(error):
        report["encoding_repaired"] = True
        return codecs.replace_errors(error)

    codecs.register_error(_BODY_DECODE_ERROR_HANDLER_NAME, _replace_and_flag)
    decoder = codecs.getincrementaldecoder("utf-8")(_BODY_DECODE_ERROR_HANDLER_NAME)

    header_buffer = _read_header_bytes(source_path, HEADER_LINE_COUNT)
    offset = _body_start_offset(header_buffer, HEADER_LINE_COUNT)
    # Unreachable in practice: every caller has already validated (via
    # read_target's own header.is_valid check) that this file's header is
    # structurally valid -- a valid header always has >= HEADER_LINE_COUNT
    # real lines, so this can never be None here.
    assert offset is not None, "stream_normalized_body_chunks called against an invalid/too-short header"

    pending_cr = False
    ends_with_terminator = False
    saw_any_byte = False

    with open(source_path, "rb") as handle:
        handle.seek(offset)
        while True:
            raw_chunk = handle.read(STREAM_CHUNK_SIZE)
            if not raw_chunk:
                break
            saw_any_byte = True
            data = (b"\r" if pending_cr else b"") + raw_chunk
            pending_cr = False
            if data.endswith(b"\r"):
                pending_cr = True
                data = data[:-1]
            if not data:
                continue
            normalized = _REAL_NEWLINE_BYTES.sub(LINESEP_BYTES, data)
            ends_with_terminator = data[-1:] in (b"\r", b"\n")
            piece = decoder.decode(normalized, False)
            if piece:
                yield piece.encode("utf-8")

    if pending_cr:
        yield LINESEP_BYTES
        ends_with_terminator = True
    final_piece = decoder.decode(b"", True)
    if final_piece:
        yield final_piece.encode("utf-8")
    if saw_any_byte and not ends_with_terminator:
        yield LINESEP_BYTES


# ADR008V01: the codes every one of the 6 per-file lifecycle commands
# (approve/reject/undo/supersede/version/revise) reaches identically,
# via resolve_repo_and_target/read_target/family_members -- each
# command's own describe() merges this in on top of its own specific
# entries (eligibility-specific codes, refdate bounds, its own write
# failures). Deliberately excludes field-is-blank: unlike
# field-contains-forbidden-character (still reachable regardless of
# stripping -- a '|' or embedded line break survives even after leading/
# trailing whitespace is removed), field-is-blank can only fire on a
# value that is non-empty but blank AFTER stripping -- reachable only
# where reject_embedded_delimiter is called on a RAW, unstripped value
# (supersede/version's own --scope/--domain flags), never where it's
# called on an already-`.strip()`-ed one (every one of these 6 commands'
# own title/scope/domain, sourced from core/header.py's _extract_cell,
# which always strips). Each command that can genuinely reach it lists
# it in its own inline dict instead.
SHARED_FAILURE_CODES = {
    FailureCodes.CANNOT_DETERMINE_ROOT_PATH: "No adr-config.adrplus was found by walking up from --file.",
    FailureCodes.FILE_NOT_FOUND: "--file does not point to an existing file (a bare name with no extension gets '.md' appended first).",
    FailureCodes.FILENAME_NOT_RECOGNIZED: "--file's own name matches neither naming scheme.",
    FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
    FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
    FailureCodes.FOLDERADR_CHANGED_AFTER_LOCK_ACQUIRED: "A concurrent config change moved folderadr while this call was acquiring the repository lock -- no write was made; retry.",
    FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "A free-text field contains '|', a line-break-like character, or (for title) a filesystem-unsafe character.",
    FailureCodes.NOT_PROPOSED: "The target's own status_create is not Proposed (and it is not a migrated placeholder either).",
    FailureCodes.ALREADY_SUPERSEDED: "The target has already been superseded.",
    FailureCodes.FAMILY_MEMBER_SUPERSEDED: "Another member of the same family has already been superseded.",
    FailureCodes.FAMILY_SCAN_INCOMPLETE: "A subdirectory under the decisions folder could not be scanned -- family membership can't be trusted from an incomplete scan.",
    FailureCodes.IO_ERROR: "A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
}


def resolve_repo_and_target(fileadr):
    """The non-content-dependent half of load_target (ADR001,
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
        raise CommandError(FailureCodes.FILE_NOT_FOUND, f"File not found: {fileadr}")

    config_path = find_repo_root(fileadr)
    if config_path is None:
        raise CommandError(
            FailureCodes.CANNOT_DETERMINE_ROOT_PATH, f"Cannot determine the repository root for: {fileadr}"
        )
    config = load_repo_config(config_path)
    return config, config_path.parent, fileadr


def resolve_target_and_config(path, *, require_config=True):
    """The path-rooted counterpart to resolve_repo_and_target above:
    config/explore/log/migrate/new all take a repository --path directly
    (rather than a decision file to walk up from), and each used to
    hand-roll the identical target-directory-not-found/config-not-found
    checks. `require_config=False` (init's own case) skips the
    config-not-found check and the load entirely -- a missing config is
    init's normal, expected state, not an error, and init decides for
    itself, from `config_path.exists()`, whether this is a fresh
    bootstrap or an already-initialized repository to re-validate."""
    target = Path(path)
    if not target.is_dir():
        raise CommandError(FailureCodes.TARGET_DIRECTORY_NOT_FOUND, f"Directory does not exist: {path}")
    config_path = target / "adr-config.adrplus"
    if not require_config:
        return target, config_path, None
    if not config_path.is_file():
        raise CommandError(FailureCodes.CONFIG_NOT_FOUND, f"No adr-config.adrplus found at: {config_path}")
    return target, config_path, load_repo_config(config_path)


def read_target(path, config, warnings=None):
    """The content-dependent half of load_target (ADR001): reads and
    parses the target file's own name and header. Call this AFTER
    acquiring the repository lock for any command that goes on to write,
    so eligibility/write decisions are made from a fresh read, not one
    captured before the lock -- the reproduced defect ADR001 closes.

    `warnings`, when given, reports a genuine marker/label disagreement
    on this exact file (ADR004V01) -- informational about a pre-existing
    condition of the file, same as excluded_candidate_warning's own
    convention, not gated behind whether this command's own write later
    succeeds.

    ADR006V01: reads only the bounded header (parse_header never looks
    past line HEADER_LINE_COUNT) -- no longer returns the file's own
    `lines` at all. A caller that goes on to preserve/carry forward the
    BODY streams it directly from `path` at write time (see
    stream_normalized_body_chunks), instead of holding it in memory
    between this read and that later write. `encoding_repaired` here
    reflects the HEADER portion only -- combine it (via `or`) with the
    body stream's own `report["encoding_repaired"]`, known only once
    that generator is fully consumed, before deciding whether to warn."""
    header_lines, encoding_repaired = read_header_lines_with_report(path)
    found = parse_any_filename(path.name, config)
    if found is None:
        raise CommandError(FailureCodes.FILENAME_NOT_RECOGNIZED, f"Filename matches no naming scheme: {path.name}")
    _, filename_info = found

    header = parse_header(header_lines, config)
    if not header.is_valid:
        # header.error is already the specific, correctly-computed reason
        # (adr-file-empty, adr-header-title-not-found,
        # status-line-date-invalid, ...) -- use it as the code itself
        # instead of discarding it behind one fixed label.
        code = header.error or FailureCodes.HEADER_INVALID
        raise CommandError(
            code,
            f"{path.name}: its header does not parse ({code}), so its status can't be read and no command "
            "acts on it. Repair it by hand.",
        )

    if warnings is not None:
        warning = marker_label_mismatch_warning(header)
        if warning:
            warnings.append(warning)

    return filename_info, header, encoding_repaired


def load_target(fileadr):
    """The common preamble approve/reject/undo/supersede/version/revise
    all share: resolve the extension default, find the file's own
    repository root by walking up for adr-config.adrplus, load+validate
    that config, then parse this file's own name and header. Recognizes
    BOTH naming schemes.

    Kept as a single call for any caller that doesn't need the lock-then-
    read split (ADR001) -- see resolve_repo_and_target/read_target above
    for that split, now used by every command that goes on to write.

    ADR006V01: no longer returns the file's own `lines` -- see
    read_target's own updated note; `encoding_repaired` here reflects
    the HEADER portion only."""
    config, root, path = resolve_repo_and_target(fileadr)
    filename_info, header, encoding_repaired = read_target(path, config)
    return config, root, path, filename_info, header, encoding_repaired


def family_members(folder, config, number, warnings=None, ignored=None):
    """Every decision (current or legacy scheme) sharing `number` whose
    header parses, with that parsed header attached.

    The filename decides identity and numbering, counting every file; the
    header decides status, counting only the ones that parse. A file with
    this number whose header does not parse -- damaged by hand, a lossy
    decode that broke it, or a legacy file never run through `migrate` --
    is left out: its status can't be read, and nothing here guesses it.
    That is an accepted limit, not a guarantee: a family made
    inconsistent that way (two live decisions after a hand-broken
    Superseded cell) is not prevented. It is made visible instead: each
    such file is reported once in `warnings`, and `explore` lists it with
    the reason.

    `ignored`, when given (a list), receives each such file as
    (ParsedFileName, HeaderParseResult, Path) -- for a caller that must
    not act on a family whose status it can't fully read (reject's
    predecessor revert), or that numbers by filename (version/revise).

    Scans strict -- an unreadable subdirectory or file is an OS error,
    not an invalid file, and is never treated as "no such member"."""
    members = []
    for _, parsed, path in scan_decisions(
        folder, config, warnings=warnings, strict=True, incomplete_code=FailureCodes.FAMILY_SCAN_INCOMPLETE
    ):
        if parsed.number != number:
            continue
        # Only the header (12 lines) decides membership -- the body is
        # never loaded just to check that.
        header = parse_header(read_header_lines(path), config)
        # Deliberately does not surface header.marker_label_mismatches
        # (ADR004V01) here -- a mismatch on a SIBLING would misattribute a
        # warning about that other file to whatever command (e.g.
        # approve) is actually acting on a different family member.
        # read_target's own warning already covers the file actually
        # being acted on.
        if not header.is_valid:
            if ignored is not None:
                ignored.append((parsed, header, path))
            if warnings is not None:
                warning = ignored_file_warning(path, header.error)
                if warning not in warnings:
                    warnings.append(warning)
            continue
        members.append((parsed, header, path))
    return members


def latest_in_family(folder, config, number, members=None):
    """The family member with the highest (version, revision).
    Returns (ParsedFileName, HeaderParseResult, Path), or None. Accepts an
    already-fetched `members` list (from family_members) so a caller can
    scan the directory once and reuse the same snapshot."""
    if members is None:
        members = family_members(folder, config, number)
    if not members:
        return None
    return max(members, key=lambda item: (item[0].version, item[0].revision or 0))


def locking_member(filename_info, members):
    """The family member that makes `filename_info`'s decision no longer
    the live one, or None when it is.

    Only the family's latest member is alive. A newer version locks every
    member of an older version, and a newer revision locks the older
    revisions of the same version -- unless every newer one is Rejected:
    rejected attempts never lock what came before them (Round 40; widened
    from "a single Rejected member" in Round 41, both decided by the
    project owner). Membership and
    status come from `members` (headers that parse); version and revision
    from the filename."""

    def blocker(newer):
        if not newer:
            return None
        live = [member for member in newer if member[1].status_update != "Rejected"]
        if not live:
            return None
        return max(live, key=lambda member: (member[0].version, member[0].revision or 0))

    newer_versions = [m for m in members if m[0].version > filename_info.version]
    locked_by = blocker(newer_versions)
    if locked_by is not None:
        return locked_by
    newer_revisions = [
        m
        for m in members
        if m[0].version == filename_info.version and (m[0].revision or 0) > (filename_info.revision or 0)
    ]
    return blocker(newer_revisions)


def raise_if_not_latest(filename_info, members, warnings):
    """not-latest-version when a newer family member locks this one (see
    locking_member), naming that member as data -- the code alone can't
    carry which file it is."""
    locked_by = locking_member(filename_info, members)
    if locked_by is None:
        return
    parsed, header, path = locked_by
    raise CommandError(
        FailureCodes.NOT_LATEST_VERSION,
        f"This decision is no longer the live one in its family: {path.name} is newer. Only the latest "
        "member can change (newer members that were all Rejected leave this one live).",
        data={
            "latest_file": str(path),
            "latest_version": parsed.version,
            "latest_revision": parsed.revision,
            "latest_status": header.status_update,
        },
        warnings=warnings,
    )


def _as_number(ref):
    """A Superseded cell's successor reference as an int, or None when it
    is not plain ASCII digits (hand-edited)."""
    ref = (ref or "").strip()
    return int(ref) if ref.isascii() and ref.isdigit() else None


def raise_if_superseded_sibling(members, warnings):
    """family-member-superseded when a member of the family is Superseded,
    naming it (data.superseded_file) and its successor's number."""
    superseded = next((m for m in members if m[1].status_change == "Superseded"), None)
    if superseded is None:
        return
    raise CommandError(
        FailureCodes.FAMILY_MEMBER_SUPERSEDED,
        f"A decision in this family has already been superseded: {superseded[2].name}. The one way back is "
        "rejecting its successor.",
        data={"superseded_file": str(superseded[2]), "successor_number": _as_number(superseded[1].superseded_by_file)},
        warnings=warnings,
    )


def raise_if_pending_sibling(members, warnings, consequence=""):
    """family-member-pending when another member is still Proposed (a
    migrated placeholder never counts), naming it (data.pending_file)."""
    pending = next((m for m in members if m[1].status_update is None and not m[1].is_migrated), None)
    if pending is None:
        return
    raise CommandError(
        FailureCodes.FAMILY_MEMBER_PENDING,
        f"Another decision in this family is still unresolved (Proposed): {pending[2].name}{consequence}. "
        "Approve or reject it first.",
        data={"pending_file": str(pending[2])},
        warnings=warnings,
    )


def raise_if_rejected_successor(members, warnings):
    """A successor (its filename carries a supersede suffix) that was
    Rejected is the end of its line, and so is its whole family: rejecting
    it put its predecessor back, and nothing may bring any of it back to
    life or branch off it -- a version of a successor carries no suffix,
    but is the successor's family all the same (Round 40, decided by the
    project owner). `members` is the target's own family."""
    rejected = next(
        (m for m in members if m[0].superseded_from is not None and m[1].status_update == "Rejected"), None
    )
    if rejected is not None:
        raise CommandError(
            FailureCodes.REJECTED_SUCCESSOR_IS_FINAL,
            "This decision belongs to a successor that was rejected: its predecessor was put back, and the "
            "successor's family is the end of its line. Supersede the predecessor again for a new successor.",
            data={"successor_file": str(rejected[2]), "predecessor_number": rejected[0].superseded_from},
            warnings=warnings,
        )


def _ineligibility_reason_for_proposed_state(header):
    """The two structural checks every ineligibility_reason_for_* below
    shares byte-for-byte: must be Proposed (or a migrated placeholder
    with no update status yet), and must not already be superseded.
    Returns None when both hold, else the shared reason -- each caller
    layers its own status_update-specific interpretation on top of this
    when it returns None, since that part genuinely differs per use case
    (see each function's own docstring for exactly how)."""
    if not (header.status_create == "Proposed" or (header.status_create is None and header.is_migrated)):
        return FailureCodes.NOT_PROPOSED
    if header.status_change is not None:
        return FailureCodes.ALREADY_SUPERSEDED
    return None


def ineligibility_reason_for_approve_or_reject(header):
    """Confirmed against the reference tool: eligible requires status_update
    to be None, full stop -- not merely "not Accepted and not Rejected".
    Returns None when eligible, else the SPECIFIC reason (a single
    collapsed not-eligible-for-* code couldn't distinguish "already
    Accepted" from "already Rejected" from "already Superseded" -- each
    calls for a different recovery action). Callers already guarantee
    header.is_valid via load_target before reaching this check.

    A structurally-valid but corrupted/hand-edited status_update (e.g.
    the "Changed" cell holding the "Proposed" or "Superseded" label text)
    could otherwise fall through to eligible here -- confirmed reachable
    live via approve on such a file. Any non-None, non-Accepted,
    non-Rejected value must be ineligible too."""
    shared_reason = _ineligibility_reason_for_proposed_state(header)
    if shared_reason is not None:
        return shared_reason
    if header.status_update is None:
        return None
    if header.status_update == "Accepted":
        return FailureCodes.ALREADY_ACCEPTED
    if header.status_update == "Rejected":
        return FailureCodes.ALREADY_REJECTED
    return FailureCodes.UNEXPECTED_STATUS


def ineligibility_reason_for_undo(header):
    """See ineligibility_reason_for_approve_or_reject's own note. Unlike
    the other three below, grants NO migrated-placeholder exception --
    undo requires a real, already-applied status_update to undo."""
    shared_reason = _ineligibility_reason_for_proposed_state(header)
    if shared_reason is not None:
        return shared_reason
    if header.status_update is None:
        return FailureCodes.STILL_PROPOSED
    return None


def ineligibility_reason_for_supersede(header):
    """Must already be Accepted (or a migrated placeholder with no
    update status yet). See ineligibility_reason_for_approve_or_reject's
    own note.

    A corrupted status_update (e.g. "Superseded" landing in the wrong
    cell) must be distinguished from a genuine Rejected value, not
    mislabeled "already-rejected" -- the boolean outcome (ineligible
    either way) is unaffected, only the reported reason."""
    shared_reason = _ineligibility_reason_for_proposed_state(header)
    if shared_reason is not None:
        return shared_reason
    if header.status_update == "Accepted" or (header.status_update is None and header.is_migrated):
        return None
    if header.status_update is None:
        return FailureCodes.STILL_PROPOSED
    if header.status_update == "Rejected":
        return FailureCodes.ALREADY_REJECTED
    return FailureCodes.UNEXPECTED_STATUS


def ineligibility_reason_for_version_or_revise(header):
    """Must already be Accepted OR Rejected (or a migrated placeholder
    with no update status yet). See
    ineligibility_reason_for_approve_or_reject's own note.

    Same mislabel class as ineligibility_reason_for_supersede -- a
    corrupted non-None, non-Accepted, non-Rejected value must not be
    labeled "still-proposed", which is only accurate when status_update
    genuinely is None."""
    shared_reason = _ineligibility_reason_for_proposed_state(header)
    if shared_reason is not None:
        return shared_reason
    if header.status_update in ("Accepted", "Rejected") or (header.status_update is None and header.is_migrated):
        return None
    if header.status_update is None:
        return FailureCodes.STILL_PROPOSED
    return FailureCodes.UNEXPECTED_STATUS


def _record_from_header(config, filename_info, header):
    """Rebuilds a DecisionRecord from an already-parsed header, ready
    for a targeted field mutation. Version/Revision come from the header
    AS READ, never recalculated;
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


def _rewrite_with_streamed_body(path, config, record, migrated, lock):
    """Shared by rewrite_status_field/mark_superseded (ADR006V01): builds
    the new header (schema-bounded, safe in memory) and streams the
    ORIGINAL body straight from `path` into the atomic write -- the file
    being rewritten is also the source of its own preserved body, safe
    because both the read and the write happen inside the same
    critical section as the caller's already-held repository lock, and
    atomic_write_chunks never opens the destination in a way that could
    be observed mid-write by the same read.

    `lock.verify_still_held()` runs a SECOND time here, as the last thing
    the chunk generator does before it exhausts -- i.e. right before
    atomic_write_chunks proceeds to its committing os.replace. The
    caller's own pre-call check (ADR001, part 3) only proves the lock was
    held before this streamed read+write began; unlike the whole-buffer
    write this replaced, streaming a real body can now take genuinely
    non-trivial time, reopening the same check-to-commit gap ADR001
    always required be kept shut (confirmed live: without this second
    check, a lock stolen mid-stream was silently ignored and the write
    committed anyway). Raises LockLostError (via `lock.verify_still_held`)
    if the lock was lost during the stream -- every caller of
    rewrite_status_field/mark_superseded already treats a LockLostError
    from this exact write the same as an OSError from it.

    Returns (attempts, body_encoding_repaired) -- `content` is no longer
    returned at all: streaming this write means the full content is
    never assembled as one in-memory value. Every real caller already
    discarded the old `content` return (confirmed by reading every call
    site before this change)."""
    header_text = build_header(config, record, migrated=migrated)
    report = {}

    def _chunks(path=path, header_text=header_text, report=report, lock=lock):
        yield header_text.encode("utf-8")
        yield from stream_normalized_body_chunks(path, report)
        lock.verify_still_held()

    attempts = atomic_write_chunks(path, _chunks)
    return attempts, report["encoding_repaired"]


def rewrite_status_field(path, config, header, filename_info, *, field, status, refdate, lock):
    """Mutates exactly one status+date pair (`field="update"` or
    `field="change"`) on the already-parsed header, rebuilds via
    build_header preserving every other field, streams the original body
    verbatim from `path` (ADR006V01), and writes the file. Returns the
    write's own attempt count too -- callers can surface it as a warning
    when it's more than 1 -- and the BODY's own encoding_repaired signal
    (combine with the header's own, from read_target, via `or`). `lock`
    is the caller's already-acquired repository lock -- re-verified right
    before this write commits, not just before it starts (see
    _rewrite_with_streamed_body)."""
    record = _record_from_header(config, filename_info, header)
    setattr(record, f"status_{field}", status)
    setattr(record, f"date_{field}", refdate if status is not None else None)

    attempts, body_encoding_repaired = _rewrite_with_streamed_body(path, config, record, header.is_migrated, lock)
    return record, body_encoding_repaired, attempts


def mark_superseded(path, config, header, filename_info, successor_number, refdate, lock):
    """Like rewrite_status_field's "change" field, but also stamps the
    successor's own zero-padded sequence number into the Superseded row.
    NOT a filename, despite DecisionRecord's `superseded_by_file` name
    (kept as-is to match the reference tool's own header row) -- confirmed the
    real value is a bare padded number, not a filename. `lock` is the
    caller's already-acquired repository lock -- see rewrite_status_field's
    own note on why it's re-verified at commit time, not just call time."""
    record = _record_from_header(config, filename_info, header)
    record.status_change = "Superseded"
    record.date_change = refdate
    record.superseded_by_file = f"{successor_number:0{config.lenseq}d}"

    attempts, body_encoding_repaired = _rewrite_with_streamed_body(path, config, record, header.is_migrated, lock)
    return record, body_encoding_repaired, attempts
