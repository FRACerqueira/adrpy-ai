"""Decision-file header: always exactly 12 lines, addressed positionally.
A row's label text is never inspected on read, only its position and the
surrounding pipe characters -- except the fields row (line 2), whose first
cell must hold the configured `headertablefields`: it is what tells this
header apart from any other table.
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

# ADR0008V01: every code parse_header can produce via its own result.error
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

# ADR0004V01: a fixed, non-translatable marker written after the status
# cell's date, in the trailing space the parser ignores for date purposes
# (as it does for the Superseded row's ": <number>" suffix). It identifies
# the status without the repository's CURRENT statusnew/statusacc/
# statusrej/statussup text, so a later label or language change cannot
# break recognition. A file without a marker falls back to label-text
# matching.
#
# ADR0004V02: matched case-insensitively, so a hand edit that changes only
# the marker's case (e.g. "<!-- accepted -->") does not silently fall back
# to label-text matching. `_CANONICAL_STATUS_BY_LOWERCASE` maps the match
# back to its canonical case, which every other consumer of `status`
# (`_STATUS_CONFIG_FIELD` lookups, `is_migrated` comparisons elsewhere)
# requires.
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
    2026-09-16--scope-note--header--migrated-word-only-when-migrated.md) --
    the word is never parsed (parse_header below only
    looks for the trailing HTML comment), so on a non-migrated file it
    would carry no information, only a misleading one.
    """
    values_label = f"{config.headertablevalues} {config.headermigrated}" if migrated else config.headertablevalues
    migrated_marker = f" <!-- {config.headermigrated} -->" if migrated else ""
    disclaimer = f"<!-- {config.headerdisclaimer} (1-{HEADER_LINE_COUNT}) -->"

    lines = [
        disclaimer,
        f"|{config.headertablefields}|{values_label}{migrated_marker}|",
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
    # ADR0004V01: which of status_create/status_update/status_change had
    # both a canonical marker and a label-text match that disagree (the
    # marker wins) -- a hand edit of the visible word after the marker was
    # written, not the routine case of a changed label matching nothing.
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

    if not _is_fields_row(lines[1], config):
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

    ADR0004V01: a canonical marker after the date's closing `)`, when
    present, decides `status` on its own, whatever the repository's
    CURRENT statusnew/statusacc/statusrej/statussup, so a later label or
    language change cannot break recognition. Without a marker, the
    label text decides.

    The label match is still attempted when a marker is present, only to
    detect `marker_label_mismatch`: a label matching nothing current (the
    routine case after a label/language change) is NOT a mismatch; only a
    label resolving to a DIFFERENT status than the marker is."""
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


def _is_fields_row(line, config):
    """Whether `line` is the header's fields row: a table row whose first
    cell holds the configured label (a header written with more around it
    in that cell is still read; every write puts the label alone)."""
    cells = line.split("|")
    return line.startswith("|") and len(cells) > 2 and config.headertablefields in cells[1]


def has_header_shape(lines, config):
    """True when any of the first HEADER_LINE_COUNT lines carries a row
    only this tool's header writes (the fields row exactly as written,
    `|{headertablefields}|` -- a hand-written table has spaces around its
    cells -- or exactly the `|--|--|` separator). Tells a damaged header
    apart from no header at all --
    looking past the first two lines, so a line inserted or deleted at
    the top doesn't hide it. A NUL byte also counts: it means the file
    was re-encoded as UTF-16/UTF-32 (PowerShell 5.1's Out-File, '>'),
    which splits the markers apart -- a damaged header, not a missing one
    (decided by the project owner).

    The second line also counts when parse_header would read it as the
    fields row (more around the label in its cell, no space at its edges)
    under the comment every header opens with, which ends in its line range
    (`(1-12) -->`): the older form, whose damaged header migrate would
    otherwise stack a second one on. Only there, and only under that
    comment, so a compact table in a note, even under its title or under a
    comment of its own (`<!-- toc -->`), is not taken for a header."""
    older_form = (
        len(lines) > 1
        and lines[0].startswith("<!-- ") and lines[0].rstrip().endswith(f"(1-{HEADER_LINE_COUNT}) -->")
        and _is_fields_row(lines[1], config)
        and lines[1].split("|")[1] == lines[1].split("|")[1].strip()
    )
    return older_form or any(
        line.startswith(f"|{config.headertablefields}|") or line.rstrip() == "|--|--|" or "\x00" in line
        for line in lines[:HEADER_LINE_COUNT]
    )


_HEADER_READ_CHUNK_SIZE = 4096
# Without this cap, a corrupted file that never reaches `count` real
# newlines would be read to EOF, one chunk at a time. 16KB is generous for
# a genuine header (a few KB at most under the config schema's
# field-length limits); a file without `count` newlines within it fails
# parse_header's too-short check.
_HEADER_READ_MAX_BYTES = _HEADER_READ_CHUNK_SIZE * 4
_REAL_NEWLINE_BYTES = re.compile(rb"\r\n|\r|\n")


def _read_header_bytes(path, count):
    """Reads only enough of `path` to recover the first `count` real lines
    (see split_real_lines), in bounded chunks, never past
    `_HEADER_READ_MAX_BYTES` even if `count` real newlines never appear.

    Re-scans the whole accumulated buffer on every iteration, never just
    the newest chunk: a `\r\n` straddling a chunk boundary would otherwise
    count twice (a lone CR, then a lone LF), ending the loop one read too
    early and truncating the `count`-th line. With the 16KB cap that is at
    most ~4 passes over 16KB, whatever the file's size.

    Retries a transient PermissionError through core/fs.py's read retry."""

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
    lines -- never the whole file -- for callers that need only the
    header (family membership checks). Invalid UTF-8 bytes decode as
    U+FFFD."""
    text = _read_header_bytes(path, count).decode("utf-8", errors="replace")
    return split_real_lines(strip_leading_boms(text))[:count]


def read_header_lines_with_report(path, count=HEADER_LINE_COUNT):
    """Same bounded read as read_header_lines, but also reports whether
    what was read needed a lossy decode -- for migrate's header-only
    eligibility scan: parse_header never looks past line `count`, and a
    corrupted byte in the body passes through untouched when migrate
    copies raw bytes. The chunked read may also decode some body content
    of a small file; content beyond the read is never checked."""
    buffer = _read_header_bytes(path, count)
    try:
        text = buffer.decode("utf-8")
        encoding_repaired = False
    except UnicodeDecodeError:
        text = buffer.decode("utf-8", errors="replace")
        encoding_repaired = True
    return split_real_lines(strip_leading_boms(text))[:count], encoding_repaired
