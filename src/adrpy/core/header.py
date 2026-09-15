"""Decision-file header: byte-for-byte replica of the real format written by
`AdrRecord.GetHeader` and read by `AdrService.ParseAdrHeaderAndContentAsync`
(harness Fase 3). The header is always exactly 12 lines, addressed
positionally -- the row *label* text is never inspected on read, only its
position and the surrounding pipe characters.
"""

import os
from dataclasses import dataclass
from datetime import date as date_cls

HEADER_LINE_COUNT = 12

_STATUS_CONFIG_FIELD = {
    "Proposed": "statusnew",
    "Accepted": "statusacc",
    "Rejected": "statusrej",
    "Superseded": "statussup",
}


@dataclass
class DecisionRecord:
    """Mirrors AdrRecord: one record feeds both the filename
    (core.naming.build_filename) and the header (build_header below)."""

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
    """Mirrors AdrRecord.GetHeader. NOTE: the real tool sources the literal
    "<!-- Migrated -->" marker text from its own UI-language resource string,
    not from `config.headermigrated` -- this uses the repo config field
    instead, a simplification to revisit once the `migrate` command (Fase 7)
    actually needs to write this marker.
    """
    migrated_marker = f"<!-- {config.headermigrated} -->" if migrated else ""
    disclaimer = f"<!-- {config.headerdisclaimer} (1-{HEADER_LINE_COUNT}) -->"

    lines = [
        disclaimer,
        f"|Adr-Plus {config.headertablefields}|{config.headertablevalues} {config.headermigrated} {migrated_marker}|",
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
    return f"|{row_label}|{status_text} ({day}){suffix}|"


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


def parse_header(lines, config):
    """Mirrors AdrService.ParseAdrHeaderAndContentAsync's header parsing."""
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

    created_text = _extract_cell(lines[8])
    if not lines[8].startswith("|") or created_text is None:
        result.error = "adr-header-status-created-not-found"
        return result
    if created_text:
        status, parsed_date, error = _parse_status_cell(created_text, config)
        if error:
            result.error = error
            return result
        result.status_create, result.date_create = status, parsed_date

    changed_text = _extract_cell(lines[9])
    if not lines[9].startswith("|") or changed_text is None:
        result.error = "adr-header-status-updated-not-found"
        return result
    if changed_text:
        status, parsed_date, error = _parse_status_cell(changed_text, config)
        if error:
            result.error = error
            return result
        result.status_update, result.date_update = status, parsed_date

    superseded_text = _extract_cell(lines[10])
    if not lines[10].startswith("|") or superseded_text is None:
        result.error = "adr-header-status-superseded-not-found"
        return result
    if superseded_text:
        status, parsed_date, error = _parse_status_cell(superseded_text, config)
        if error:
            result.error = error
            return result
        colon_index = superseded_text.find(":")
        if colon_index < 0:
            result.error = "adr-status-supersede-format-invalid"
            return result
        result.status_change, result.date_change = status, parsed_date
        result.superseded_by_file = superseded_text[colon_index + 1 :].strip()

    if not (lines[11].startswith("<!-- ") and lines[11].rstrip().endswith(" -->")):
        result.error = "adr-header-comment-not-found"
        return result

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
    open_paren = text.find("(")
    close_paren = text.find(")")
    if open_paren < 0 or close_paren < 0 or close_paren < open_paren:
        return None, None, "status-line-format-invalid"

    status_text = text[:open_paren].strip()
    label_to_status = {
        config.statusnew: "Proposed",
        config.statusacc: "Accepted",
        config.statusrej: "Rejected",
        config.statussup: "Superseded",
    }
    status = next(
        (status for label, status in label_to_status.items() if label.lower() == status_text.lower()),
        None,
    )
    if status is None:
        return None, None, "status-line-unknown-status"

    date_text = text[open_paren + 1 : close_paren].strip()
    try:
        parsed_date = date_cls.fromisoformat(date_text)
    except ValueError:
        return None, None, "status-line-date-invalid"

    return status, parsed_date, None


def is_structurally_valid(header):
    """Full parse succeeded: every row of the fixed 12-line table matched the
    expected shape and every status cell parsed cleanly. Used wherever a
    specific target file's header must be trustworthy enough to act on."""
    return header.is_valid


def counts_as_family_member(header):
    """Looser test used when scanning the ADR folder to resolve sequence and
    version membership -- mirrors AdrService.cs's
    `aux.Header.IsValid || aux.Header.IsMigrated`: a migrated file with a
    still-blank Version/Revision/Created/Changed counts as a member of its
    family even though it fails the strict structural check above."""
    return header.is_valid or header.is_migrated
