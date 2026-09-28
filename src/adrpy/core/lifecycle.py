"""Shared lifecycle-transition helpers: date-reference validation,
title-uniqueness/next-number resolution, and the read-mutate-rewrite
mechanics every status-transition command
(approve/reject/undo/supersede/version/revise) shares -- one function per
concern, not copies."""

import codecs
import os
from dataclasses import dataclass, replace as replace_fields
from datetime import date as date_cls
from pathlib import Path

from adrpy.core.atomic_write import (
    LINESEP_BYTES,
    STREAM_CHUNK_SIZE,
    atomic_write_chunks,
)
from adrpy.core.casing import unique_title_key
from adrpy.core.config import (
    LENREVISION_MAX,
    LENVERSION_MAX,
    SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES,
    VALID_SEPARATORS,
    _STATUS_LABEL_FIELDS,
    load_repo_config,
)
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.family import is_successor, locking_member
from adrpy.core.consistency import decision_names, unheadered_legacy_warning, validate_repository
from adrpy.core.decision_log import decision_log_dir_for, reject_folderlog_change_if_entries_exist
from adrpy.core.header import (
    _REAL_NEWLINE_BYTES,
    HEADER_LINE_COUNT,
    DecisionRecord,
    _read_header_bytes,
    build_header,
    parse_header,
    read_header_lines_with_report,
)
from adrpy.core.fs import (
    cleanup_orphaned_temp_files,
    commit_write,
    discard_write,
    landed_after_failure,
    prepare_write,
    scan_tree,
)
from adrpy.core.naming import REWRITE_TOO_LONG_REMEDY, parse_any_filename, reject_linked_file, reject_too_long_filename
from adrpy.core.output import explain
from adrpy.core.text import ascii_digits_int, shell_argument
from adrpy.core.security import (
    is_within,
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import (
    attach_warnings,
    excluded_candidate_warning,
    marker_label_mismatch_warning,
    orphan_cleanup_warning,
    retry_warning,
)


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


# ADR004V02: two groups, not one flat list -- `migrationpattern` only
# affects recognition of LEGACY-scheme files (naming.py's
# parse_legacy_filename is its only reader); every other guarded field
# is blanket (blocks on any recognized decision, any scheme).
#
# `separator` looks like it should be current-scheme-scoped the same
# way (naming.py's parse_filename, the CURRENT scheme, is its only
# direct reader), but parse_any_filename tries the CURRENT scheme
# FIRST, falling back to legacy only if it doesn't match: a separator
# value that already appears in a legacy-scheme filename can make
# parse_filename newly match a file that previously only matched
# parse_legacy_filename -- silently RECLASSIFYING a legacy decision as
# current-scheme, under a different number/title. `migrationpattern`
# has no mirror risk -- parse_filename never reads it, so a
# current-scheme file can never be reclassified legacy by a
# migrationpattern change. `prefix` is blanket for the same reason as
# separator: every current-scheme name starts with it.
_BLANKET_GUARD_FIELDS = _STATUS_LABEL_FIELDS + ("separator", "prefix")
# The naming fields whose change alone can make an unrecognized file
# parse as a decision, each with its own refusal code.
_ADOPTION_CODES = {
    "separator": FailureCodes.SEPARATOR_CHANGE_WOULD_ADOPT_UNRELATED_FILES,
    "prefix": FailureCodes.PREFIX_CHANGE_WOULD_ADOPT_UNRELATED_FILES,
}
_LEGACY_SCHEME_GUARD_FIELDS = ("migrationpattern",)
# Every config field whose change validate_config_change guards.
GUARDED_CONFIG_FIELDS = ("folderadr", "folderlog") + _BLANKET_GUARD_FIELDS + _LEGACY_SCHEME_GUARD_FIELDS


def guarded_fields_changed(old_config, new_config):
    """The GUARDED_CONFIG_FIELDS whose value differs between the two."""
    return [field for field in GUARDED_CONFIG_FIELDS if getattr(old_config, field) != getattr(new_config, field)]


def _recognized(scan, config, warnings):
    """(scheme, ParsedFileName, path) for every `.md` of `scan` that is a
    decision under `config` (core/consistency.decision_names: a name
    matching a naming scheme, less what the phase rule leaves out);
    reports the candidates the scan excluded for escaping the folder,
    when `warnings` is given."""
    if warnings is not None:
        warning = excluded_candidate_warning(list(scan.excluded))
        if warning:
            warnings.append(warning)
    names, _unheadered = decision_names(scan, config)
    return [(name.scheme, name.parsed, name.path) for name in names]


def validate_config_change(old_config, new_config, old_folder, *, target, scan=None, warnings=None):
    """The one guard over a config change (`config` and `init --seed`):
    refuses a change of a guarded field that would make existing
    decisions or decision-log entries invisible, unrecognized or
    reclassified, or silently adopt unrelated files. Every check reads
    the decisions folder through one scan (`scan`, the caller's
    scan_tree of `old_folder`, or one taken here); the existing files are
    always read with `old_config`, the rules they were written under.
    Fails closed when that scan is incomplete: `existing == []` is only
    trustworthy from a complete scan.

    - folderadr: only while the OLD folder has no recognized decision
      (folderadr-change-blocked-by-existing-decisions); a NEW folder that
      already exists must hold nothing that `new_config` would recognize
      (folderadr-change-would-adopt-unrelated-files). A new folder that
      does not exist yet is not scanned.
    - status labels, separator and prefix: only while no decision (any
      scheme) is recognized; migrationpattern: only while no LEGACY-scheme
      one that has a valid header (already migrated) is -- a hand-written
      file it merely matches by name is not a decision yet, so a wrong
      pattern can be fixed before migrate
      (status-or-separator-change-blocked-by-existing-decisions,
      data.existing_decisions counting only what the blocking fields
      affect). A separator or prefix change must also not newly recognize
      a file (separator-/prefix-change-would-adopt-unrelated-files) --
      checked with a config where only that field changed, so
      migrationpattern's own intended adoption (ADR002V01) is never
      blamed on it.
    - folderlog: core/decision_log.reject_folderlog_change_if_entries_exist.

    Each group keeps its own scan-incomplete code."""
    changed = guarded_fields_changed(old_config, new_config)
    blanket_fields_changed = [field for field in _BLANKET_GUARD_FIELDS if field in changed]
    legacy_scheme_fields_changed = [field for field in _LEGACY_SCHEME_GUARD_FIELDS if field in changed]
    status_fields_changed = blanket_fields_changed + legacy_scheme_fields_changed
    if scan is None and ("folderadr" in changed or status_fields_changed):
        # A missing folder is reported unreadable, as before (config
        # creates it first; init --seed does not).
        scan = scan_tree(old_folder)

    if "folderadr" in changed:
        _check_folderadr_change(old_config, new_config, scan, target, warnings)
    if status_fields_changed:
        _check_status_or_separator_change(
            old_config, new_config, scan, blanket_fields_changed, legacy_scheme_fields_changed, warnings
        )
    if "folderlog" in changed:
        reject_folderlog_change_if_entries_exist(
            decision_log_dir_for(target, old_config),
            old_config.folderlog,
            new_config.folderlog,
            target=target,
            warnings=warnings,
        )


def _check_folderadr_change(old_config, new_config, scan, target, warnings):
    old_folderadr, new_folderadr = old_config.folderadr, new_config.folderadr
    if scan.unreadable:
        unreadable = list(scan.unreadable)
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGE_SCAN_INCOMPLETE,
            f"Cannot safely determine whether '{old_folderadr}' still has decisions: "
            f"{len(unreadable)} subdirectory/subdirectories could not be scanned.",
            data={"folderadr": old_folderadr, "unreadable": unreadable},
            warnings=warnings,
        )
    existing = _recognized(scan, old_config, warnings)
    if existing:
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS,
            f"Cannot change folderadr from '{old_folderadr}' to '{new_folderadr}': "
            f"{len(existing)} existing decision(s) under '{old_folderadr}' would become invisible.",
            data={"folderadr": old_folderadr, "existing_decisions": len(existing)},
            warnings=warnings,
        )

    new_folder = resolve_within(target, new_folderadr)
    if not new_folder.is_dir():
        return
    new_scan = scan_tree(new_folder)
    if new_scan.unreadable:
        new_unreadable = list(new_scan.unreadable)
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGE_SCAN_INCOMPLETE,
            f"Cannot safely determine whether '{new_folderadr}' already has unrelated content: "
            f"{len(new_unreadable)} subdirectory/subdirectories could not be scanned.",
            data={"folderadr": new_folderadr, "unreadable": new_unreadable},
            warnings=warnings,
        )
    adopted = sorted(str(path) for _, _, path in _recognized(new_scan, new_config, warnings))
    if adopted:
        raise CommandError(
            FailureCodes.FOLDERADR_CHANGE_WOULD_ADOPT_UNRELATED_FILES,
            f"Cannot change folderadr to '{new_folderadr}': {len(adopted)} file(s) already there would "
            "silently become recognized decisions.",
            data={"folderadr": new_folderadr, "adopted_files": adopted},
            warnings=warnings,
        )


def _check_status_or_separator_change(
    old_config, new_config, scan, blanket_fields_changed, legacy_scheme_fields_changed, warnings
):
    changed_fields = blanket_fields_changed + legacy_scheme_fields_changed
    if scan.unreadable:
        # Not scheme-scoped: an unreadable subdirectory's own contents
        # (and therefore scheme) are unknowable.
        unreadable = list(scan.unreadable)
        raise CommandError(
            FailureCodes.STATUS_OR_SEPARATOR_CHANGE_SCAN_INCOMPLETE,
            f"Cannot safely determine whether existing decisions would be affected by changing "
            f"{', '.join(changed_fields)}: {len(unreadable)} subdirectory/subdirectories could not be "
            "scanned.",
            data={"changed_fields": changed_fields, "unreadable": unreadable},
            warnings=warnings,
        )

    existing = _recognized(scan, old_config, warnings)
    legacy_existing_count = sum(
        1 for scheme, _, path in existing if scheme == "legacy" and has_valid_header(path, old_config)
    )

    blocking_fields = []
    if blanket_fields_changed and existing:
        blocking_fields += blanket_fields_changed
    if legacy_scheme_fields_changed and legacy_existing_count:
        blocking_fields += legacy_scheme_fields_changed

    if blocking_fields:
        # A blanket field blocking puts every recognized decision at risk;
        # only migrationpattern blocking alone narrows it to the legacy ones.
        affected_count = len(existing) if blanket_fields_changed and existing else legacy_existing_count
        raise CommandError(
            FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS,
            f"Cannot change {', '.join(blocking_fields)}: {affected_count} existing decision(s) would no "
            "longer be recognized.",
            data={"changed_fields": blocking_fields, "existing_decisions": affected_count},
            warnings=warnings,
        )

    old_recognized_paths = {path for _, _, path in existing}
    naming_changed = [field for field in _ADOPTION_CODES if field in blanket_fields_changed]
    # Each naming field alone, then all of them together: a name can need
    # both a new prefix and a new separator to parse (e.g. a re-seed that
    # changes both). migrationpattern stays at its old value throughout.
    candidates = [(field, [field]) for field in naming_changed]
    if len(naming_changed) > 1:
        candidates.append((naming_changed[0], naming_changed))
    for field, fields in candidates:
        code = _ADOPTION_CODES[field]
        field_only_config = replace_fields(old_config, **{name: getattr(new_config, name) for name in fields})
        adopted = sorted(
            (
                path
                for _, _, path in _recognized(scan, field_only_config, None)
                if path not in old_recognized_paths
            ),
            key=str,
        )
        if adopted:
            raise CommandError(
                code,
                f"Cannot change {' and '.join(fields)}: {len(adopted)} file(s) not currently recognized as a decision "
                "would silently become one.",
                data={"adopted_files": [str(path) for path in adopted]},
                warnings=warnings,
            )


def legacy_pattern_preview(paths, config):
    """What `config`'s migrationpattern reads from each of `paths` it
    recognizes as a legacy-scheme decision: [{file, number, version,
    title}], in path order -- `config --migrationpattern`'s preview."""
    preview = []
    for path in sorted(paths, key=str):
        found = parse_any_filename(path.name, config)
        if found is not None and found[0] == "legacy":
            parsed = found[1]
            preview.append({"file": str(path), "number": parsed.number, "version": parsed.version, "title": parsed.title})
    return preview


# What to do about a likely misreading: before migrate the pattern can
# still change; after it, the migrated files block any change (ADR004V02).
PATTERN_ADVICE_BEFORE_MIGRATE = (
    "Preview another with `adrpy explore --path . --migrationpattern <pattern>` (it writes nothing), set the "
    "right one with `adrpy config --migrationpattern` (it writes the config), then run `adrpy migrate`."
)
PATTERN_ADVICE_AFTER_MIGRATE = (
    "These files are migrated now, and migrationpattern can no longer change while they are: to redo them, "
    "restore their content from before this migrate (e.g. `git checkout -- <file>`) before any other command, "
    "set the right pattern with `adrpy config --migrationpattern`, and run `adrpy migrate` again."
)


def legacy_pattern_warnings(preview, advice):
    """Warnings for what usually means migrationpattern misreads the names
    in `preview` (legacy_pattern_preview's shape): titles that start with
    a separator (T points at it), or a number far above all the others
    (N reading part of a date or of the title). `advice` ends each one
    (PATTERN_ADVICE_BEFORE_MIGRATE or PATTERN_ADVICE_AFTER_MIGRATE)."""
    warnings = []
    separated = [entry["file"] for entry in preview if (entry["title"] or "")[:1] in VALID_SEPARATORS]
    if separated:
        warnings.append(
            f"{len(separated)} title(s) start with a separator: {', '.join(separated)}. The pattern's T "
            "(title start) likely points at the separator: for `0001-title.md`, 'N00:04T05' reads number "
            f"0001 and title 'title'. {advice}"
        )
    ranked = sorted(preview, key=lambda entry: entry["number"], reverse=True)
    if len(ranked) >= 2 and ranked[0]["number"] >= 100 and ranked[0]["number"] > 10 * ranked[1]["number"]:
        warnings.append(
            f"Number {ranked[0]['number']} ({ranked[0]['file']}) is far above the others (next highest: "
            f"{ranked[1]['number']}): the pattern's N (start:length) may be reading part of a date or of the "
            f"title, or that file is not a decision (a note, say): move it out of the decisions folder before "
            f"migrate. {advice}"
        )
    return warnings


def has_valid_header(path, config):
    """True when `path`'s header parses under `config` -- a decision
    already migrated (or created by the tool), not a hand-written file
    that only matches migrationpattern by name. A file that cannot be
    read counts as one (fails closed)."""
    try:
        lines, _encoding_repaired = read_header_lines_with_report(path)
    except OSError:
        return True
    return parse_header(lines, config).is_valid


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
    found. The path is made absolute with `..` collapsed but no link
    followed (os.path.abspath): a relative path's own parents stop at '.',
    an uncollapsed `..` walks through folders that are not the file's
    ancestors, and following a link would let a path under one repository
    find another (the boundary checks then refuse a link out of it)."""
    directory = Path(os.path.abspath(file_path)).parent
    while True:
        candidate = directory / "adr-config.adrplus"
        if candidate.is_file():
            return candidate
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


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
    header), reproducing the whole-file read it replaced byte-for-byte
    (ADR006V01; tests/test_lifecycle.py keeps that read as its reference) -- every real line
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
    # Unreachable in practice: every caller has already validated (the
    # repository validation in prepare) that this file's header is
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


# ADR008V01: the one text for every code the 6 per-file lifecycle
# commands (approve/reject/undo/supersede/version/revise) reach through
# prepare() -- the ones all of them reach while resolving the target and
# validating the repository,
# plus the ineligibility and family-guard codes, of which each command
# lists only those its own TRANSITIONS row can raise (failure_codes
# below). Each command's own describe() adds its specific entries
# (refdate bounds, its own write failures) on top. The ineligibility
# texts are also the error detail raised at run time, so each one must
# hold for every command that can raise it. Deliberately excludes
# field-contains-forbidden-character and field-is-blank: only a flag
# value or a filename segment is validated in prepare() (supersede's
# --title/--scope/--domain and filename title, version's --scope/
# --domain) -- a header cell breaking the same rules makes the header
# invalid, one of repository-inconsistent's data.errors. The two
# commands that can reach them list them in their own inline dict.
SHARED_FAILURE_CODES = {
    FailureCodes.CANNOT_DETERMINE_ROOT_PATH: "No adr-config.adrplus was found by walking up from --file.",
    FailureCodes.FILE_NOT_FOUND: "--file does not point to an existing file (a bare name with no extension gets '.md' appended first).",
    FailureCodes.FILENAME_NOT_RECOGNIZED: (
        "--file's own name matches neither naming scheme, or only migrationpattern matches it and it has no "
        "header while the repository already has a decision with a header migrate did not write (then it "
        "is not a decision; data.file)."
    ),
    FailureCodes.TARGET_OUTSIDE_FOLDERADR: "--file is not inside the repository's decisions folder (folderadr); only a decision there is acted on -- move it into folderadr (then run migrate if it has no header).",
    FailureCodes.REPOSITORY_INCONSISTENT: "The decisions folder breaks at least one consistency rule (the same ones `adrpy check` reports); data.errors lists every one, with its file and a repair hint. Nothing is written until the repository is repaired.",
    FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
    FailureCodes.TARGET_IS_A_LINK: (
        "A file this command would rewrite (--file; for reject of a successor, also the predecessor it "
        "reverts) is a symbolic link -- nothing was written (a write would replace the link, not the file it "
        "points to); give the real file (data.real_file), and check warns about the link."
    ),
    FailureCodes.FILENAME_TOO_LONG: (
        "The name of a file this command would rewrite (--file; for reject of a successor, also the "
        "predecessor it reverts) is longer than the 234 bytes this tool can rewrite (data.filename) -- nothing "
        "was written; rename it by hand to a shorter title part, keeping its number, version, revision and any "
        "--NNN suffix."
    ),
    FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
    FailureCodes.STILL_PROPOSED: "This decision's status does not allow this command: undo needs it Accepted or Rejected, version and revise Accepted or Rejected (or a migrated placeholder), supersede Accepted (or a migrated placeholder). Whether to accept or reject it is the user's decision.",
    FailureCodes.ALREADY_ACCEPTED: "This decision is already Accepted; run undo first to reconsider it.",
    FailureCodes.ALREADY_REJECTED: "This decision is already Rejected; run undo first to reconsider it (supersede needs it Accepted), unless it belongs to a rejected successor's family, whose line is final -- supersede its predecessor again.",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.FAMILY_MEMBER_SUPERSEDED: "Another member of the same family has already been superseded.",
    FailureCodes.FAMILY_MEMBER_PENDING: "Another member of the same family is still unresolved (Proposed).",
    FailureCodes.NOT_LATEST_VERSION: "A newer member of this family locks this one -- only the latest member can change, unless every newer one is Rejected (data.latest_file names the newer file).",
    FailureCodes.REJECTED_SUCCESSOR_IS_FINAL: "This decision belongs to the family of a successor that was rejected -- the end of its line; supersede its predecessor again instead (data.successor_file, data.predecessor_number).",
    FailureCodes.IO_ERROR: "A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
}


def resolve_target_and_config(path, *, require_config=True):
    """The path-rooted counterpart to prepare's --file resolution below:
    check/config/explore/log/migrate/new all take a repository --path directly
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
        raise CommandError(
            FailureCodes.CONFIG_NOT_FOUND,
            f"No adr-config.adrplus found at: {config_path.absolute()} -- run `adrpy init --path {shell_argument(path, '<repository folder>')}` to create "
            "one, or give --path the repository's root.",
        )
    return target, config_path, load_repo_config(config_path)


def family_members(snapshot, number):
    """Every decision of family `number` in `snapshot` (a validated
    core/consistency Snapshot), as (ParsedFileName, HeaderParseResult,
    Path), in (version, revision) order. The snapshot is read once; nothing
    here touches the disk. Every header in it parses: the validator
    refuses a repository where one does not."""
    return [(decision.name, decision.header, decision.path) for decision in snapshot.by_number.get(number, ())]


def latest_in_family(members):
    """The family member with the highest (version, revision), from
    family_members' list. Returns (ParsedFileName, HeaderParseResult,
    Path), or None for an empty family."""
    if not members:
        return None
    return max(members, key=lambda item: (item[0].version, item[0].revision or 0))


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
        data={
            "superseded_file": str(superseded[2]),
            "successor_number": ascii_digits_int(superseded[1].superseded_by_file),
        },
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
    but is the successor's family all the same (decided by the project
    owner). `members` is the target's own family."""
    rejected = next(
        (m for m in members if is_successor(m[0]) and m[1].status_update == "Rejected"), None
    )
    if rejected is not None:
        raise CommandError(
            FailureCodes.REJECTED_SUCCESSOR_IS_FINAL,
            "This decision belongs to a successor that was rejected: its predecessor was put back, and the "
            "successor's family is the end of its line. Supersede the predecessor again for a new successor.",
            data={"successor_file": str(rejected[2]), "predecessor_number": rejected[0].superseded_from},
            warnings=warnings,
        )


def ineligibility_reason_for_approve_or_reject(header):
    """Eligible requires status_update to be None, full stop -- not merely
    "not Accepted and not Rejected".
    Returns None when eligible, else the SPECIFIC reason (a single
    collapsed not-eligible-for-* code couldn't distinguish "already
    Accepted" from "already Rejected" from "already Superseded" -- each
    calls for a different recovery action). The header comes from a
    validated repository, so its status cells are in the closed set
    (core/consistency): Changed is blank, Accepted or Rejected."""
    if header.status_change is not None:
        return FailureCodes.ALREADY_SUPERSEDED
    if header.status_update is None:
        return None
    if header.status_update == "Accepted":
        return FailureCodes.ALREADY_ACCEPTED
    return FailureCodes.ALREADY_REJECTED


def ineligibility_reason_for_undo(header):
    """See ineligibility_reason_for_approve_or_reject's own note. Unlike
    the other three below, grants NO migrated-placeholder exception --
    undo requires a real, already-applied status_update to undo."""
    if header.status_change is not None:
        return FailureCodes.ALREADY_SUPERSEDED
    if header.status_update is None:
        return FailureCodes.STILL_PROPOSED
    return None


def ineligibility_reason_for_supersede(header):
    """Must already be Accepted (or a migrated placeholder with no
    update status yet). See ineligibility_reason_for_approve_or_reject's
    own note."""
    if header.status_change is not None:
        return FailureCodes.ALREADY_SUPERSEDED
    if header.status_update == "Accepted" or (header.status_update is None and header.is_migrated):
        return None
    if header.status_update is None:
        return FailureCodes.STILL_PROPOSED
    return FailureCodes.ALREADY_REJECTED


def ineligibility_reason_for_version_or_revise(header):
    """Must already be Accepted OR Rejected (or a migrated placeholder
    with no update status yet). See
    ineligibility_reason_for_approve_or_reject's own note."""
    if header.status_change is not None:
        return FailureCodes.ALREADY_SUPERSEDED
    if header.status_update in ("Accepted", "Rejected") or (header.status_update is None and header.is_migrated):
        return None
    return FailureCodes.STILL_PROPOSED


@dataclass(frozen=True)
class Transition:
    """One row of TRANSITIONS: what prepare() checks for one command, in
    this order -- the eligibility of the target's own status (`reasons`
    lists every code `eligibility` can return), the family guards, the
    refdate bounds, the fields read for the write (a flag value or a
    filename segment validated) and, last, the new number. Every row
    runs after the repository was validated (core/consistency).

    - `revision_required`: revision-not-configured when lenrevision is 0,
      checked once the repository is validated and the target found.
    - `numbering`: "version" or "revision" when the row works out a new
      number (family-not-found and the lenversion/lenrevision bound),
      after the fields.
    - `guards`: family-guard failure codes, in the order they are checked.
    - `pending_consequence`: appended to family-member-pending's detail.
    - `refdate_anchor`: None (no --refdate at all), "create" (not before
      the creation date) or "update-or-create" (not before the last
      update date, else the creation date).
    - `fields`: (field, source) in validation order. Source "header" is
      the target's own header cell, "flag-or-header" the flag when given
      else the header cell (or ""), "flag-or-filename" the flag when given
      else the target's own filename segment. Only a flag value or a
      filename segment is validated (field-contains-forbidden-character);
      parse_header already applied the same rules to a header cell."""

    eligibility: object
    reasons: tuple
    guards: tuple
    refdate_anchor: object
    fields: tuple
    numbering: object = None
    revision_required: bool = False
    pending_consequence: str = ""


_HEADER_FIELDS = (("title", "header"), ("scope", "header"), ("domain", "header"))
_APPROVE_OR_REJECT_REASONS = (
    FailureCodes.ALREADY_ACCEPTED,
    FailureCodes.ALREADY_REJECTED,
    FailureCodes.ALREADY_SUPERSEDED,
)
_VERSION_OR_REVISE_REASONS = (
    FailureCodes.STILL_PROPOSED,
    FailureCodes.ALREADY_SUPERSEDED,
)
_VERSION_OR_REVISE_GUARDS = (
    FailureCodes.FAMILY_MEMBER_SUPERSEDED,
    FailureCodes.FAMILY_MEMBER_PENDING,
    FailureCodes.NOT_LATEST_VERSION,
    FailureCodes.REJECTED_SUCCESSOR_IS_FINAL,
)

# The asymmetries between rows are deliberate current behavior, not
# oversights: approve/reject have no family-member-pending; version
# validates scope/domain before title, the others title first.
TRANSITIONS = {
    "approve": Transition(
        eligibility=ineligibility_reason_for_approve_or_reject,
        reasons=_APPROVE_OR_REJECT_REASONS,
        guards=(FailureCodes.FAMILY_MEMBER_SUPERSEDED, FailureCodes.NOT_LATEST_VERSION),
        refdate_anchor="create",
        fields=_HEADER_FIELDS,
    ),
    "reject": Transition(
        eligibility=ineligibility_reason_for_approve_or_reject,
        reasons=_APPROVE_OR_REJECT_REASONS,
        guards=(FailureCodes.FAMILY_MEMBER_SUPERSEDED, FailureCodes.NOT_LATEST_VERSION),
        refdate_anchor="create",
        fields=_HEADER_FIELDS,
    ),
    "undo": Transition(
        eligibility=ineligibility_reason_for_undo,
        reasons=(FailureCodes.STILL_PROPOSED, FailureCodes.ALREADY_SUPERSEDED),
        guards=(
            FailureCodes.FAMILY_MEMBER_SUPERSEDED,
            FailureCodes.FAMILY_MEMBER_PENDING,
            FailureCodes.NOT_LATEST_VERSION,
            FailureCodes.REJECTED_SUCCESSOR_IS_FINAL,
        ),
        pending_consequence=" -- undo would leave two",
        refdate_anchor=None,
        fields=_HEADER_FIELDS,
    ),
    "version": Transition(
        eligibility=ineligibility_reason_for_version_or_revise,
        reasons=_VERSION_OR_REVISE_REASONS,
        numbering="version",
        guards=_VERSION_OR_REVISE_GUARDS,
        refdate_anchor="update-or-create",
        fields=(("scope", "flag-or-header"), ("domain", "flag-or-header"), ("title", "header")),
    ),
    "revise": Transition(
        eligibility=ineligibility_reason_for_version_or_revise,
        reasons=_VERSION_OR_REVISE_REASONS,
        revision_required=True,
        numbering="revision",
        guards=_VERSION_OR_REVISE_GUARDS,
        refdate_anchor="update-or-create",
        fields=_HEADER_FIELDS,
    ),
    "supersede": Transition(
        eligibility=ineligibility_reason_for_supersede,
        reasons=(
            FailureCodes.STILL_PROPOSED,
            FailureCodes.ALREADY_REJECTED,
            FailureCodes.ALREADY_SUPERSEDED,
        ),
        guards=(
            FailureCodes.FAMILY_MEMBER_SUPERSEDED,
            FailureCodes.FAMILY_MEMBER_PENDING,
            FailureCodes.NOT_LATEST_VERSION,
        ),
        refdate_anchor="update-or-create",
        fields=(("scope", "flag-or-header"), ("domain", "flag-or-header"), ("title", "flag-or-filename")),
    ),
}

_ROW_SPECIFIC_CODES = {code for row in TRANSITIONS.values() for code in row.reasons + row.guards}
# Raised by prepare only for the rows that rewrite --file (no numbering):
# version and revise never do (their own filename-too-long is about the
# file they create).
_REWRITE_ONLY_CODES = {FailureCodes.TARGET_IS_A_LINK, FailureCodes.FILENAME_TOO_LONG}


def failure_codes(command, own):
    """describe()'s failure_codes for one of the 6 commands: the
    ineligibility codes its row can raise, then its `own` entries, then
    its row's family guards and the codes all 6 share (in
    SHARED_FAILURE_CODES order), then the config codes. A header that
    does not parse is one of repository-inconsistent's data.errors (its
    parse-failure code in `detail`), never a failure of its own."""
    row = TRANSITIONS[command]
    head = {code: text for code, text in SHARED_FAILURE_CODES.items() if code in row.reasons}
    tail = {
        code: text
        for code, text in SHARED_FAILURE_CODES.items()
        if (code in row.guards or code not in _ROW_SPECIFIC_CODES)
        and not (row.numbering is not None and code in _REWRITE_ONLY_CODES)
    }
    return build_failure_codes(head, own, tail, CONFIG_FAILURE_CODES)


@dataclass(frozen=True)
class Context:
    """What prepare() hands back: the target (its repository's config and
    root, the path as given, its filename identity and header, whether
    its header read needed a lossy decode), its decisions folder, the
    validated repository (`snapshot`, core/consistency), the new version
    or revision number when the row numbers one, the checked refdate (None without an anchor), the title/scope/
    domain the write uses, and the warnings accumulated so far -- the same
    list the command keeps appending to."""

    config: object
    root: object
    path: object
    filename_info: object
    header: object
    encoding_repaired: bool
    folder: object
    snapshot: object
    new_version: object
    new_revision: object
    refdate: object
    title: object
    scope: object
    domain: object
    warnings: list


def widening_hint(field, needed, maximum, no_room="this family has no room for another one"):
    """The way out when a new number does not fit its field's width:
    `config` widens it, up to that field's maximum."""
    if needed > maximum:
        return f" {field}'s maximum ({maximum}) is too narrow for it: {no_room}."
    return f" Widen it with `adrpy config --path <repository> --{field} {needed}`, then run this command again."


def _new_version(config, members, warnings):
    latest = latest_in_family(members)
    if latest is None:
        raise CommandError(
            FailureCodes.FAMILY_NOT_FOUND, "Could not resolve this decision's own family.", warnings=warnings
        )
    new_version = latest[0].version + 1
    if len(str(new_version)) > config.lenversion:
        raise CommandError(
            FailureCodes.LENVERSION_TOO_SMALL_FOR_NEW_VERSION,
            f"New version {new_version} does not fit in lenversion={config.lenversion}."
            + widening_hint("lenversion", len(str(new_version)), LENVERSION_MAX),
            data={"new_version": new_version, "lenversion": config.lenversion},
            warnings=warnings,
        )
    return new_version


def _new_revision(config, filename_info, members, warnings):
    latest = latest_in_family(members)
    if latest is None:
        raise CommandError(
            FailureCodes.FAMILY_NOT_FOUND, "Could not resolve this decision's own family.", warnings=warnings
        )
    # The next revision after the highest one this version already holds
    # (the target's revision + 1 would collide when branching off an
    # older revision). A migrated placeholder's blank cells play no part.
    new_revision = (
        max(
            ((entry[0].revision or 0) for entry in members if entry[0].version == filename_info.version),
            default=filename_info.revision or 0,
        )
        + 1
    )
    if len(str(new_revision)) > config.lenrevision:
        raise CommandError(
            FailureCodes.LENREVISION_TOO_SMALL_FOR_NEW_REVISION,
            f"New revision {new_revision} does not fit in lenrevision={config.lenrevision}."
            + widening_hint("lenrevision", len(str(new_revision)), LENREVISION_MAX),
            data={"new_revision": new_revision, "lenrevision": config.lenrevision},
            warnings=warnings,
        )
    return new_revision


def _check_guard(code, row, filename_info, members, warnings):
    if code == FailureCodes.FAMILY_MEMBER_SUPERSEDED:
        raise_if_superseded_sibling(members, warnings)
    elif code == FailureCodes.FAMILY_MEMBER_PENDING:
        raise_if_pending_sibling(members, warnings, row.pending_consequence)
    elif code == FailureCodes.NOT_LATEST_VERSION:
        raise_if_not_latest(filename_info, members, warnings)
    elif code == FailureCodes.REJECTED_SUCCESSOR_IS_FINAL:
        raise_if_rejected_successor(members, warnings)


def _validated_field(name, source, flags, header, filename_info):
    """title/scope/domain, from their SOURCE: a flag when the row allows
    one and it is given, else the target's header cell or filename
    segment. A header cell is used as it is: parse_header applies the
    free-text rules to it, and a header that breaks one does not parse
    (the repository was refused before this point). A flag value or a
    filename segment is validated here -- a title lands inside a filename
    component, where e.g. ':' (an NTFS Alternate-Data-Stream separator)
    breaks the rename."""
    if source == "header":
        return getattr(header, name)
    if source == "flag-or-header" and name not in flags:
        return getattr(header, name) or ""
    value = flags[name] if name in flags else getattr(filename_info, name)
    reject_embedded_delimiter(value, name)
    if name == "title":
        reject_filesystem_unsafe_title(value, name)
        reject_title_with_no_case_transform_content(value, name)
    return value


def _resolve_file(fileadr):
    """--file's path (a bare name gets '.md'), its repository's config
    (found by walking up for adr-config.adrplus) and root, and its
    filename identity ((scheme, ParsedFileName)) -- nothing read from the file itself yet."""
    fileadr = Path(fileadr)
    if fileadr.suffix == "":
        fileadr = fileadr.with_suffix(".md")
    if not fileadr.is_file():
        raise CommandError(FailureCodes.FILE_NOT_FOUND, f"File not found: {fileadr}")
    config_path = find_repo_root(fileadr)
    if config_path is None:
        detail = (
            f"Cannot determine the repository root for: {fileadr} -- no adr-config.adrplus in its folder or any "
            "folder above it (run `adrpy init --path .` at the repository's root)."
        )
        real = fileadr.resolve()
        if ".." in fileadr.parts and Path(os.path.abspath(fileadr)).resolve() != real:
            detail += (
                f" The path is read as written: a `..` after a symlinked folder is not followed. Give the "
                f"file's real path instead: {real}."
            )
        raise CommandError(FailureCodes.CANNOT_DETERMINE_ROOT_PATH, detail)
    config = load_repo_config(config_path)
    found = parse_any_filename(fileadr.name, config)
    if found is None:
        raise CommandError(FailureCodes.FILENAME_NOT_RECOGNIZED, f"Filename matches no naming scheme: {fileadr.name}")
    return fileadr, config, config_path.parent, found


def _target_in(snapshot, path, number):
    """The Decision of `snapshot` that is `path` (compared by real path,
    within its family). Not there only when its name is not a decision's
    after all -- e.g. an extension other than .md."""
    real = path.resolve()
    target = next((decision for decision in snapshot.by_number.get(number, ()) if decision.path.resolve() == real), None)
    if target is None:
        raise CommandError(FailureCodes.FILENAME_NOT_RECOGNIZED, f"Not a decision file: {path.name}")
    return target


def prepare(command, fileadr, flags):
    """The preamble the 6 file-targeted lifecycle commands share, driven by
    their TRANSITIONS row: resolve --file and its repository, refuse a
    target outside the decisions folder, clean up orphaned temp files,
    validate the whole repository (core/consistency.validate_repository:
    repository-inconsistent, with data.errors, before any other rule),
    then the checks of the row, in its order. The target and its family
    come from that one validated snapshot; nothing is read twice. Writes
    nothing to a decision (only removes orphaned temp files); each command
    does its own writes afterward. Every failure after the repository is
    resolved carries the warnings accumulated so far.

    The target's own filename is checked before the repository is
    validated: a file that is not a decision, or not in the decisions
    folder, is refused as such, whatever state the repository is in."""
    row = TRANSITIONS[command]
    warnings = []
    path, config, root, (scheme, parsed) = _resolve_file(fileadr)
    with attach_warnings(warnings):
        folder = resolve_within(root, config.folderadr)
        if not is_within(folder, path):
            raise CommandError(
                FailureCodes.TARGET_OUTSIDE_FOLDERADR,
                f"{path} is not inside the decisions folder ({config.folderadr}). Only a decision there is acted "
                "on: move it into folderadr (then run migrate if it has no header).",
                data={"file": str(path), "folderadr": config.folderadr},
            )
        # One walk of the folder feeds the orphan sweep and the validator.
        scan = scan_tree(folder)
        warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings, scan=scan))
        if warning:
            warnings.append(warning)
        if scheme == "legacy":
            real = path.resolve()
            if any(left_out.resolve() == real for left_out in decision_names(scan, config)[1]):
                raise CommandError(
                    FailureCodes.FILENAME_NOT_RECOGNIZED,
                    f"Not a decision file: {path.name} matches migrationpattern but has no header, and this "
                    "repository already has a file with a valid header migrate did not write (migrate no longer "
                    "runs here). Give it a header by hand, or move it out of the decisions folder.",
                    data={"file": str(path)},
                )
        snapshot = validate_repository(folder, config, scan=scan)
        for warning in (excluded_candidate_warning(list(snapshot.excluded)), unheadered_legacy_warning(snapshot, config)):
            if warning:
                warnings.append(warning)

        target = _target_in(snapshot, path, parsed.number)
        filename_info, header = target.name, target.header
        # A name past what this tool can rewrite fails the rewrite with a
        # raw OSError: refused here, before anything is written, by the
        # commands that rewrite --file (version and revise never do).
        if row.numbering is None:
            reject_linked_file(path)
            reject_too_long_filename(path.name, REWRITE_TOO_LONG_REMEDY)
        # ADR004V01: a marker/label disagreement on the target itself, not
        # on a sibling (that would misattribute it to this command).
        warning = marker_label_mismatch_warning(header)
        if warning:
            warnings.append(warning)

        if row.revision_required and config.lenrevision == 0:
            raise CommandError(
                FailureCodes.REVISION_NOT_CONFIGURED,
                "This repository's config has lenrevision == 0 (revisions are off). Turn them on with "
                f"`adrpy config --path {shell_argument(root, '<repository root>')} --lenrevision 2`; the decisions created afterwards also carry a "
                "revision in their names (R01).",
            )

        # A specific reason code, not one collapsed not-eligible-for-*,
        # so the caller knows which recovery action applies.
        reason = row.eligibility(header)
        if reason is not None:
            raise CommandError(reason, SHARED_FAILURE_CODES[reason], warnings=warnings)
        members = family_members(snapshot, filename_info.number)
        for code in row.guards:
            _check_guard(code, row, filename_info, members, warnings)

        refdate = None
        if row.refdate_anchor is not None:
            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            if row.refdate_anchor == "create":
                not_before = header.date_create
            else:
                not_before = header.date_update or header.date_create
            if not_before is not None:
                validate_refdate_not_before(refdate, not_before)

        values = {
            name: _validated_field(name, source, flags, header, filename_info) for name, source in row.fields
        }

        # The new number last: a width refusal is only ever the real
        # blocker, never one that widening would trade for another refusal.
        new_version = new_revision = None
        if row.numbering == "version":
            new_version = _new_version(config, members, warnings)
        elif row.numbering == "revision":
            new_revision = _new_revision(config, filename_info, members, warnings)

    return Context(
        config=config,
        root=root,
        path=path,
        filename_info=filename_info,
        header=header,
        encoding_repaired=target.encoding_repaired,
        folder=folder,
        snapshot=snapshot,
        new_version=new_version,
        new_revision=new_revision,
        refdate=refdate,
        title=values["title"],
        scope=values["scope"],
        domain=values["domain"],
        warnings=warnings,
    )


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


def _streamed_rewrite_chunks(path, config, record, migrated, report):
    """The chunk factory of a rewrite of `path` (ADR006V01): the new
    header (schema-bounded, safe in memory), then the ORIGINAL body
    streamed straight from `path` -- the file being rewritten is also the
    source of its own preserved body, safe because the write goes to a
    temp file and only replaces the destination once the stream is fully
    consumed. Sets report["encoding_repaired"] once the body is read."""
    header_text = build_header(config, record, migrated=migrated)

    def _chunks(path=path, header_text=header_text, report=report):
        yield header_text.encode("utf-8")
        yield from stream_normalized_body_chunks(path, report)

    return _chunks


def _status_field_record(config, header, filename_info, field, status, refdate):
    record = _record_from_header(config, filename_info, header)
    setattr(record, f"status_{field}", status)
    setattr(record, f"date_{field}", refdate if status is not None else None)
    return record


def rewrite_status_field(path, config, header, filename_info, *, field, status, refdate):
    """Mutates exactly one status+date pair (`field="update"` or
    `field="change"`) on the already-parsed header, rebuilds via
    build_header preserving every other field, streams the original body
    verbatim from `path` (ADR006V01), and writes the file. Returns the
    write's own attempt count too -- callers can surface it as a warning
    when it's more than 1 -- and the BODY's own encoding_repaired signal
    (combine with the header's own, from prepare, via `or`)."""
    record = _status_field_record(config, header, filename_info, field, status, refdate)
    report = {}
    attempts = atomic_write_chunks(path, _streamed_rewrite_chunks(path, config, record, header.is_migrated, report))
    return record, report["encoding_repaired"], attempts


def prepare_status_field_rewrite(path, config, header, filename_info, *, field, status, refdate):
    """rewrite_status_field's content, prepared but not committed (see
    core/fs.prepare_write): returns (record, body_encoding_repaired,
    prepared) -- for a command that writes several files and commits
    them only once all are prepared (commit_in_order)."""
    record = _status_field_record(config, header, filename_info, field, status, refdate)
    report = {}
    prepared = prepare_write(path, _streamed_rewrite_chunks(path, config, record, header.is_migrated, report))
    return record, report["encoding_repaired"], prepared


def prepare_mark_superseded(path, config, header, filename_info, successor_number, refdate):
    """Like prepare_status_field_rewrite's "change" field, but also stamps
    the successor's own zero-padded sequence number into the Superseded
    row. NOT a filename, despite DecisionRecord's `superseded_by_file`
    name: the value is a bare padded number, as in AdrPlus's header row."""
    record = _record_from_header(config, filename_info, header)
    record.status_change = "Superseded"
    record.date_change = refdate
    record.superseded_by_file = f"{successor_number:0{config.lenseq}d}"
    report = {}
    prepared = prepare_write(path, _streamed_rewrite_chunks(path, config, record, header.is_migrated, report))
    return record, report["encoding_repaired"], prepared


def commit_in_order(steps, warnings, *, hint, repair=None):
    """Commits several prepared writes in the given order. `steps` is a
    list of (prepared, exclusive, warnings_once_applied); each file's own
    warnings join `warnings` only once that file is committed. On a
    failure, every temp not yet committed is discarded.

    A failure before any file of the operation is on disk (none committed
    here) propagates unchanged, for the
    caller to map to its own nothing-written code. A failure after that
    raises multi-file-write-partially-applied (an OSError) or
    interrupted (anything else: Ctrl+C, an unexpected error), with
    data.applied and data.pending naming the files, and `hint` telling
    how to finish. `repair`, when given ({file, row}), is the exact
    header row to put in `file` by hand to make the repository
    consistent again; it goes into data.repair and the detail.

    What was written is decided from the disk (core/fs.write_landed): an
    interrupt right after a rename/replace returned counts that file as
    written. An interrupt once every file is written reports them all,
    with no hint or repair (the repository is consistent)."""
    applied = []
    try:
        for prepared, exclusive, applied_warnings in steps:
            attempts = prepared.attempts + commit_write(prepared, exclusive=exclusive) - 1
            applied.append(str(prepared.path))
            warnings.extend(applied_warnings)
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)
    except BaseException as error:
        if len(applied) < len(steps) and not isinstance(error, FileExistsError):
            current = steps[len(applied)]
            if landed_after_failure(current[0]):
                applied.append(str(current[0].path))
                warnings.extend(current[2])
        # The failing one's own temp too: already gone when commit_write
        # itself failed, and discarding is idempotent.
        unwritten = steps[len(applied) :]
        for step in unwritten:
            discard_write(step[0])
        if not applied:
            raise
        pending = [str(step[0].path) for step in unwritten]
        if not pending:
            raise CommandError(
                FailureCodes.INTERRUPTED,
                f"Interrupted ({explain(error)}) after every file was written: {', '.join(applied)}. "
                "The operation is complete.",
                data={"applied": applied, "pending": []},
                warnings=warnings,
            ) from error
        if isinstance(error, OSError):
            code, cause = FailureCodes.MULTI_FILE_WRITE_PARTIALLY_APPLIED, f"{unwritten[0][0].path}: {error}"
        else:
            code, cause = FailureCodes.INTERRUPTED, f"Interrupted ({explain(error)})"
        raise CommandError(
            code,
            f"{cause}. Already written: {', '.join(applied)}; not written: "
            f"{', '.join(pending)}. {hint}"
            + (f" In {repair['file']}, replace the row starting '|{repair['row'].split('|')[1]}|' with: {repair['row']}" if repair else ""),
            data={"applied": applied, "pending": pending, **({"repair": repair} if repair else {})},
            warnings=warnings,
        ) from error


def discard_prepared(prepared):
    """Drops every prepared write in `prepared` (None entries skipped)."""
    for item in prepared:
        if item is not None:
            discard_write(item)
