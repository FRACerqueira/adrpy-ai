"""Decision-file header: the 12-line format adrpy shares with AdrPlus
1.0.0. The header is always exactly 12 lines, addressed
positionally -- the row *label* text is never inspected on read, only its
position and the surrounding pipe characters.
"""

import re
from dataclasses import dataclass
from datetime import date as date_cls

from adrpy.core.atomic_write import join_lines_with_trailing_terminator, split_real_lines
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.fs import read_with_permission_retry
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
)
from adrpy.core.text import is_ascii_digits, strip_leading_boms

HEADER_LINE_COUNT = 12

# ADR008V01: every code parse_header can produce via its own result.error
# (never raised here directly: the repository validator, core/consistency,
# reports it as the start of an invalid-header entry's `detail`), one
# static one-line condition each. Reachable by the commands that validate
# the repository -- migrate and explore call parse_header directly but
# only ever read .is_valid/.error, never raise on it.
SHARED_FAILURE_CODES = {
    FailureCodes.HEADER_INVALID: "The header failed structural validation, for a reason not covered by a more specific code below.",
    FailureCodes.ADR_FILE_EMPTY: "The file has no content at all.",
    FailureCodes.ADR_FILE_TOO_SHORT: "The file has fewer than the 12 required header lines.",
    FailureCodes.ADR_HEADER_COMMENT_NOT_FOUND: "Line 1 (or line 12) is not the '<!-- ... -->' disclaimer comment this format requires.",
    FailureCodes.ADR_HEADER_INVALID_FORMAT: "Line 2 or line 3 does not match the fixed table-header shape this format requires.",
    FailureCodes.ADR_HEADER_TITLE_NOT_FOUND: "The Title row's own cell is missing or malformed.",
    FailureCodes.ADR_HEADER_VERSION_NOT_FOUND: "The Version row's own cell is missing, malformed, or not a plain digit run.",
    FailureCodes.ADR_HEADER_REVISION_NOT_FOUND: "The Revision row's own cell is missing, malformed, or not a plain digit run.",
    FailureCodes.ADR_HEADER_SCOPE_NOT_FOUND: "The Scope row's own cell is missing or malformed.",
    FailureCodes.ADR_HEADER_DOMAIN_NOT_FOUND: "The Domain row's own cell is missing or malformed.",
    FailureCodes.ADR_HEADER_STATUS_CREATED_NOT_FOUND: "The Created status row's own cell is missing or malformed.",
    FailureCodes.ADR_HEADER_STATUS_UPDATED_NOT_FOUND: "The Changed status row's own cell is missing or malformed.",
    FailureCodes.ADR_HEADER_STATUS_SUPERSEDED_NOT_FOUND: "The Superseded status row's own cell is missing or malformed.",
    FailureCodes.ADR_STATUS_SUPERSEDE_FORMAT_INVALID: "The Superseded row's own status is set, but its successor-reference suffix (': <number>') is missing.",
    FailureCodes.STATUS_LINE_FORMAT_INVALID: "A status cell's own parenthesized-date shape ('label (date)') could not be parsed at all.",
    FailureCodes.STATUS_LINE_UNKNOWN_STATUS: "A status cell's own label text does not match any of statusnew/statusacc/statusrej/statussup, and no canonical marker is present either.",
    FailureCodes.STATUS_LINE_DATE_INVALID: "A status cell's own parenthesized date is not a valid ISO date.",
    FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "The Title, Scope or Domain cell breaks a free-text rule: a '|' (an extra cell in its row), a line-break-like character, or (for Title) a filesystem-unsafe character or no character other than whitespace, '_' or '-'.",
}

_STATUS_CONFIG_FIELD = {
    "Proposed": "statusnew",
    "Accepted": "statusacc",
    "Rejected": "statusrej",
    "Superseded": "statussup",
}

# ADR004V01: a fixed, non-translatable marker written after the status
# cell's date -- in the trailing space both this parser and AdrPlus
# 1.0.0's ParseStatusLine ignore for date purposes (as they already do
# for the Superseded row's own ": <number>" suffix below).
# Recognizing it takes recognition of a decision written under this
# scheme off the repository's CURRENT statusnew/statusacc/statusrej/
# statussup text entirely, so a later label or language change can never
# again break it. Absent (any file written before this existed) falls
# back to the same label-text match as before.
#
# ADR004V02: matched case-insensitively -- a hand edit that changes only
# the marker's case (e.g. "<!-- accepted -->") used to fail this match
# outright and silently fall back to label-text matching with zero
# signal, reopening exactly the fragility this marker exists to close.
# `_CANONICAL_STATUS_BY_LOWERCASE` maps the match back to its canonical,
# correctly-cased form -- every other consumer of `status` (this
# module's own `_STATUS_CONFIG_FIELD` lookups, `is_migrated`
# comparisons elsewhere) requires the exact canonical case, never the
# case actually found in the file.
_CANONICAL_MARKER_PATTERN = re.compile(
    r"<!--\s*(" + "|".join(_STATUS_CONFIG_FIELD.keys()) + r")\s*-->", re.IGNORECASE
)
_CANONICAL_STATUS_BY_LOWERCASE = {status.lower(): status for status in _STATUS_CONFIG_FIELD}


@dataclass
class DecisionRecord:
    """One record feeds both the filename (core.naming.build_filename)
    and the header (build_header below)."""

    number: int
    title: str
    version: int
    revision: int | None = None
    scope: str = ""
    domain: str = ""
    status_create: str | None = None
    date_create: date_cls | None = None
    status_update: str | None = None
    date_update: date_cls | None = None
    status_change: str | None = None
    date_change: date_cls | None = None
    superseded_by_file: str | None = None
    superseded: int | None = None


def build_header(config, record, migrated=False):
    """The "Migrated" word in the Values column's own label comes from
    `config.headermigrated`, and appears only when `migrated` (decision-log:
    accepted-divergence--2026-09-16--header--migrated-word-only-when-
    migrated.md) -- the word is never parsed (parse_header below only
    looks for the trailing HTML comment), so on a non-migrated file it
    would carry no information, only a misleading one.
    """
    values_label = f"{config.headertablevalues} {config.headermigrated}" if migrated else config.headertablevalues
    migrated_marker = f" <!-- {config.headermigrated} -->" if migrated else ""
    disclaimer = f"<!-- {config.headerdisclaimer} (1-{HEADER_LINE_COUNT}) -->"

    lines = [
        disclaimer,
        f"|Adr-Plus {config.headertablefields}|{values_label}{migrated_marker}|",
        "|--|--|",
        f"|{config.headertitlefile}|{record.title}|",
        (
            f"|{config.headerversion}||"
            if migrated
            else f"|{config.headerversion}|{record.version:0{config.lenversion}d}|"
        ),
        (
            f"|{config.headerrevision}|{record.revision:0{config.lenrevision}d}|"
            if record.revision is not None
            else f"|{config.headerrevision}||"
        ),
        f"|{config.headerscope}|{record.scope}|" if record.scope else f"|{config.headerscope}||",
        f"|{config.headerdomain}|{record.domain}|" if record.domain else f"|{config.headerdomain}||",
        status_row(config, config.headertitlestatuscreated, record.status_create, record.date_create),
        status_row(config, config.headertitlestatuschanged, record.status_update, record.date_update),
        status_row(
            config,
            config.headertitlestatussuperseded,
            record.status_change,
            record.date_change,
            suffix=(
                f" : {record.superseded_by_file}"
                if record.status_change == "Superseded" and record.superseded_by_file
                else ""
            ),
        ),
        disclaimer,
    ]
    return join_lines_with_trailing_terminator(lines)


def status_row(config, row_label, status, date_value, suffix=""):
    """One status row exactly as build_header writes it."""
    if status is None:
        return f"|{row_label}||"
    status_text = getattr(config, _STATUS_CONFIG_FIELD[status])
    day = (date_value or date_cls.today()).isoformat()
    marker = f" <!-- {status} -->"
    return f"|{row_label}|{status_text} ({day}){marker}{suffix}|"


@dataclass
class HeaderParseResult:
    is_valid: bool = False
    is_migrated: bool = False
    error: str | None = None
    # The rule's own message, when `error` comes from a free-text rule
    # (title/scope/domain) rather than the header's structure.
    error_detail: str | None = None
    disclaimer: str = ""
    title: str = ""
    version: int | None = None
    revision: int | None = None
    scope: str = ""
    domain: str = ""
    status_create: str | None = None
    date_create: date_cls | None = None
    status_update: str | None = None
    date_update: date_cls | None = None
    status_change: str | None = None
    date_change: date_cls | None = None
    superseded_by_file: str | None = None
    # ADR004V01: names which of status_create/status_update/status_change
    # carried BOTH a canonical marker and a label-text match, where the two
    # disagreed (the marker still wins for the field's own resolved value
    # above) -- a hand edit of the visible word after the marker was
    # written, not the routine, expected case of a label/language change
    # simply no longer matching an existing marker-less file's old text.
    marker_label_mismatches: tuple = ()


def parse_header(lines, config):
    result = HeaderParseResult()

    if len(lines) == 0:
        result.error = FailureCodes.ADR_FILE_EMPTY
        return result
    if len(lines) < HEADER_LINE_COUNT:
        result.error = FailureCodes.ADR_FILE_TOO_SHORT
        return result

    if not (lines[0].startswith("<!-- ") and lines[0].rstrip().endswith(" -->")):
        result.error = FailureCodes.ADR_HEADER_COMMENT_NOT_FOUND
        return result
    result.disclaimer = lines[0].replace("<!-- ", "").replace(" -->", "").strip()

    if not lines[1].startswith("|Adr-Plus "):
        result.error = FailureCodes.ADR_HEADER_INVALID_FORMAT
        return result
    if lines[1].rstrip().endswith(" -->|") and "<!-- " in lines[1]:
        result.is_migrated = True

    if not lines[2].startswith("|--|--|"):
        result.error = FailureCodes.ADR_HEADER_INVALID_FORMAT
        return result

    title = _extract_cell(lines[3], free_text=True)
    if not lines[3].startswith("|") or title is None:
        result.error = FailureCodes.ADR_HEADER_TITLE_NOT_FOUND
        return result
    if not _passes_free_text_rules(result, title, "title"):
        return result
    result.title = title

    version_text = _extract_cell(lines[4])
    if not lines[4].startswith("|") or version_text is None:
        result.error = FailureCodes.ADR_HEADER_VERSION_NOT_FOUND
        return result
    if version_text:
        if not is_ascii_digits(version_text):
            result.error = FailureCodes.ADR_HEADER_VERSION_NOT_FOUND
            return result
        result.version = int(version_text)

    revision_text = _extract_cell(lines[5])
    if not lines[5].startswith("|") or revision_text is None:
        result.error = FailureCodes.ADR_HEADER_REVISION_NOT_FOUND
        return result
    if revision_text:
        if not is_ascii_digits(revision_text):
            result.error = FailureCodes.ADR_HEADER_REVISION_NOT_FOUND
            return result
        result.revision = int(revision_text)

    scope = _extract_cell(lines[6], free_text=True)
    if not lines[6].startswith("|") or scope is None:
        result.error = FailureCodes.ADR_HEADER_SCOPE_NOT_FOUND
        return result
    if not _passes_free_text_rules(result, scope, "scope"):
        return result
    result.scope = scope

    domain = _extract_cell(lines[7], free_text=True)
    if not lines[7].startswith("|") or domain is None:
        result.error = FailureCodes.ADR_HEADER_DOMAIN_NOT_FOUND
        return result
    if not _passes_free_text_rules(result, domain, "domain"):
        return result
    result.domain = domain

    mismatches = []

    created_text = _extract_cell(lines[8])
    if not lines[8].startswith("|") or created_text is None:
        result.error = FailureCodes.ADR_HEADER_STATUS_CREATED_NOT_FOUND
        return result
    if created_text:
        status, parsed_date, mismatch, error = _parse_status_cell(created_text, config)
        if error:
            result.error = error
            return result
        result.status_create, result.date_create = status, parsed_date
        if mismatch:
            mismatches.append("status_create")

    changed_text = _extract_cell(lines[9])
    if not lines[9].startswith("|") or changed_text is None:
        result.error = FailureCodes.ADR_HEADER_STATUS_UPDATED_NOT_FOUND
        return result
    if changed_text:
        status, parsed_date, mismatch, error = _parse_status_cell(changed_text, config)
        if error:
            result.error = error
            return result
        result.status_update, result.date_update = status, parsed_date
        if mismatch:
            mismatches.append("status_update")

    superseded_text = _extract_cell(lines[10])
    if not lines[10].startswith("|") or superseded_text is None:
        result.error = FailureCodes.ADR_HEADER_STATUS_SUPERSEDED_NOT_FOUND
        return result
    if superseded_text:
        status, parsed_date, mismatch, error = _parse_status_cell(superseded_text, config)
        if error:
            result.error = error
            return result
        colon_index = superseded_text.find(":")
        if colon_index < 0:
            result.error = FailureCodes.ADR_STATUS_SUPERSEDE_FORMAT_INVALID
            return result
        result.status_change, result.date_change = status, parsed_date
        result.superseded_by_file = superseded_text[colon_index + 1 :].strip()
        if mismatch:
            mismatches.append("status_change")

    if not (lines[11].startswith("<!-- ") and lines[11].rstrip().endswith(" -->")):
        result.error = FailureCodes.ADR_HEADER_COMMENT_NOT_FOUND
        return result

    result.marker_label_mismatches = tuple(mismatches)
    result.is_valid = True
    return result


def _passes_free_text_rules(result, value, field_name):
    """The rules every command applies to title/scope/domain before a
    write (core/security.py), applied once here instead: a cell that
    breaks one makes the header invalid, with the rule's own code in
    `result.error` and its message in `result.error_detail`."""
    try:
        reject_embedded_delimiter(value, field_name)
        if field_name == "title":
            reject_filesystem_unsafe_title(value, field_name)
            reject_title_with_no_case_transform_content(value, field_name)
    except CommandError as error:
        result.error = error.code
        result.error_detail = error.detail
        return False
    return True


def _extract_cell(line, free_text=False):
    """The value cell of a `|label|value|` row: everything between the
    label's closing '|' and the row's last one, so an extra cell is never
    silently dropped. In a free-text row (title, scope, domain) a '|'
    left in the value is refused by the free-text rules
    (field-contains-forbidden-character); in any other row the cell is
    malformed (None: the row's own not-found code)."""
    start = line.find("|", 1)
    if start == -1:
        return None
    end = line.rstrip().rfind("|")
    if end <= start:
        return None
    cell = line[start + 1 : end].strip()
    if not free_text and "|" in cell:
        return None
    return cell


def _parse_status_cell(text, config):
    """Returns (status, date, marker_label_mismatch, error).

    ADR004V01: a canonical marker after the date's closing `)`, when
    present, decides `status` on its own -- the repository's CURRENT
    statusnew/statusacc/statusrej/statussup no longer has any say, so a
    later label or language change can never again break recognition of
    a file written under this scheme. Falls back to the pre-existing
    label-text match when no marker is present (any file written before
    this existed).

    The label match is still attempted even when a marker is present,
    purely to detect `marker_label_mismatch`: the label legitimately no
    longer matching anything current (the routine case after a label/
    language change) is NOT a mismatch -- only a label that still
    resolves, but to a DIFFERENT status than the marker, is."""
    open_paren = text.find("(")
    close_paren = text.find(")")
    if open_paren < 0 or close_paren < 0 or close_paren < open_paren:
        return None, None, False, FailureCodes.STATUS_LINE_FORMAT_INVALID

    status_text = text[:open_paren].strip()
    label_to_status = {
        config.statusnew: "Proposed",
        config.statusacc: "Accepted",
        config.statusrej: "Rejected",
        config.statussup: "Superseded",
    }
    label_status = next(
        (status for label, status in label_to_status.items() if label.lower() == status_text.lower()),
        None,
    )

    marker_match = _CANONICAL_MARKER_PATTERN.search(text[close_paren + 1 :])
    if marker_match:
        status = _CANONICAL_STATUS_BY_LOWERCASE[marker_match.group(1).lower()]
        mismatch = label_status is not None and label_status != status
    else:
        status = label_status
        mismatch = False
        if status is None:
            return None, None, False, FailureCodes.STATUS_LINE_UNKNOWN_STATUS

    date_text = text[open_paren + 1 : close_paren].strip()
    try:
        parsed_date = date_cls.fromisoformat(date_text)
    except ValueError:
        return None, None, False, FailureCodes.STATUS_LINE_DATE_INVALID

    return status, parsed_date, mismatch, None


def describe_header_error(header):
    """The header's failure code followed by its own message when the rule
    that failed gave one (it names the field), e.g.
    "field-contains-forbidden-character: Field 'title' cannot contain ..."."""
    if header.error and header.error_detail:
        return f"{header.error}: {header.error_detail}"
    return header.error


def has_header_shape(lines):
    """True when any of the first HEADER_LINE_COUNT lines carries a row
    only this tool's header writes (`|Adr-Plus ` field row, or exactly
    the `|--|--|` separator). Tells a damaged header apart from no header at all --
    looking past the first two lines, so a line inserted or deleted at
    the top doesn't hide it. Both markers are plain ASCII, so a lossy
    decode never removes them. A NUL byte also counts: it means the file
    was re-encoded as UTF-16/UTF-32 (PowerShell 5.1's Out-File, '>'),
    which splits the markers apart -- a damaged header, not a missing one
    (decided by the project owner)."""
    return any(
        "|Adr-Plus " in line or line.rstrip() == "|--|--|" or "\x00" in line for line in lines[:HEADER_LINE_COUNT]
    )


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
    window the write side (core/fs.py) already retries. Shares
    core/fs.py's loop rather than being an independent copy."""

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


def read_header_lines(path, count=HEADER_LINE_COUNT):
    """Reads only enough of `path` to recover the first `count` real
    lines -- never the whole file. Used wherever only the header is
    needed (family membership checks): reading a candidate's entire
    body, however large, just to look at its first 12 lines would be
    wasteful. Tolerates invalid bytes the same way read_lines does."""
    text = _read_header_bytes(path, count).decode("utf-8", errors="replace")
    return split_real_lines(strip_leading_boms(text))[:count]


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
    return split_real_lines(strip_leading_boms(text))[:count], encoding_repaired
