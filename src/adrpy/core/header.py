"""Decision-file header: byte-for-byte replica of the reference tool's own
format. The header is always exactly 12 lines, addressed
positionally -- the row *label* text is never inspected on read, only its
position and the surrounding pipe characters.
"""

import os
import re
from dataclasses import dataclass
from datetime import date as date_cls

HEADER_LINE_COUNT = 12

_STATUS_CONFIG_FIELD = {
    "Proposed": "statusnew",
    "Accepted": "statusacc",
    "Rejected": "statusrej",
    "Superseded": "statussup",
}

# ADR004V01: a fixed, non-translatable marker written after the status
# cell's date -- in the trailing space both this parser and the real
# AdrPlus's own ParseStatusLine already ignore for date purposes (proven
# in production by the Superseded row's own ": <number>" suffix below).
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
    """NOTE: the reference tool sources the literal
    "<!-- Migrated -->" marker text from its own UI-language resource string,
    not from `config.headermigrated` -- this uses the repo config field
    instead, a simplification adopted when the `migrate` command was
    first built to write this marker.

    Deliberate divergence from the reference tool: the "Migrated" word in the
    Values column's own label is now conditional on `migrated`, unlike its
    literal "Values Migrated" label on every file regardless
    (decision-log: accepted-divergence--2026-09-16--header--migrated-word-
    only-when-migrated.md) -- the word is never parsed by either side
    (parse_header below only looks for the trailing HTML comment), so it
    carried no information on a non-migrated file, only a misleading one.
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
        _status_row(config, config.headertitlestatuscreated, record.status_create, record.date_create),
        _status_row(config, config.headertitlestatuschanged, record.status_update, record.date_update),
        _status_row(
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
    return os.linesep.join(lines) + os.linesep


def _status_row(config, row_label, status, date_value, suffix=""):
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
        result.error = "adr-file-empty"
        return result
    if len(lines) < HEADER_LINE_COUNT:
        result.error = "adr-file-too-short"
        return result

    if not (lines[0].startswith("<!-- ") and lines[0].rstrip().endswith(" -->")):
        result.error = "adr-header-comment-not-found"
        return result
    result.disclaimer = lines[0].replace("<!-- ", "").replace(" -->", "").strip()

    if not lines[1].startswith("|Adr-Plus "):
        result.error = "adr-header-invalid-format"
        return result
    if lines[1].rstrip().endswith(" -->|") and "<!-- " in lines[1]:
        result.is_migrated = True

    if not lines[2].startswith("|--|--|"):
        result.error = "adr-header-invalid-format"
        return result

    title = _extract_cell(lines[3])
    if not lines[3].startswith("|") or title is None:
        result.error = "adr-header-title-not-found"
        return result
    result.title = title

    version_text = _extract_cell(lines[4])
    if not lines[4].startswith("|") or version_text is None:
        result.error = "adr-header-version-not-found"
        return result
    if version_text:
        if not version_text.isdigit():
            result.error = "adr-header-version-not-found"
            return result
        result.version = int(version_text)

    revision_text = _extract_cell(lines[5])
    if not lines[5].startswith("|") or revision_text is None:
        result.error = "adr-header-revision-not-found"
        return result
    if revision_text:
        if not revision_text.isdigit():
            result.error = "adr-header-revision-not-found"
            return result
        result.revision = int(revision_text)

    scope = _extract_cell(lines[6])
    if not lines[6].startswith("|") or scope is None:
        result.error = "adr-header-scope-not-found"
        return result
    result.scope = scope

    domain = _extract_cell(lines[7])
    if not lines[7].startswith("|") or domain is None:
        result.error = "adr-header-domain-not-found"
        return result
    result.domain = domain

    mismatches = []

    created_text = _extract_cell(lines[8])
    if not lines[8].startswith("|") or created_text is None:
        result.error = "adr-header-status-created-not-found"
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
        result.error = "adr-header-status-updated-not-found"
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
        result.error = "adr-header-status-superseded-not-found"
        return result
    if superseded_text:
        status, parsed_date, mismatch, error = _parse_status_cell(superseded_text, config)
        if error:
            result.error = error
            return result
        colon_index = superseded_text.find(":")
        if colon_index < 0:
            result.error = "adr-status-supersede-format-invalid"
            return result
        result.status_change, result.date_change = status, parsed_date
        result.superseded_by_file = superseded_text[colon_index + 1 :].strip()
        if mismatch:
            mismatches.append("status_change")

    if not (lines[11].startswith("<!-- ") and lines[11].rstrip().endswith(" -->")):
        result.error = "adr-header-comment-not-found"
        return result

    result.marker_label_mismatches = tuple(mismatches)
    result.is_valid = True
    return result


def _extract_cell(line):
    start = line.find("|", 1)
    if start == -1:
        return None
    end = line.find("|", start + 1)
    if end == -1:
        return None
    return line[start + 1 : end].strip()


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
        return None, None, False, "status-line-format-invalid"

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
            return None, None, False, "status-line-unknown-status"

    date_text = text[open_paren + 1 : close_paren].strip()
    try:
        parsed_date = date_cls.fromisoformat(date_text)
    except ValueError:
        return None, None, False, "status-line-date-invalid"

    return status, parsed_date, mismatch, None


def counts_as_family_member(header):
    """Looser test used when scanning the ADR folder to resolve sequence
    and version membership: a migrated file with a still-blank
    Version/Revision/Created/Changed counts as a member of its family
    even though it fails the strict structural check above."""
    return header.is_valid or header.is_migrated
