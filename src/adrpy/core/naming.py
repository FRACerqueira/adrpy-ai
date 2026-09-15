"""Filename parsing for both naming schemes (harness Fase 6 + Fase 7 item 1).

**Current scheme** -- ported from PatternParser.ParseAdrPattern's regex
(`^([A-Za-z]*)(\\d+)(?:[Vv](\\d+)(?:[Rr](\\d+))?)?$`): number/version/revision
are variable-length digit runs, NOT padded to the config's
lenseq/lenversion/lenrevision -- deliberately so, since a file whose digits
no longer fit a newly-*shrunk* config must still be recognized (needed by
`init`'s digit-overflow check).

**Legacy scheme** -- ported from PatternParser.ParseMigratePattern +
AdrService.ParseMigrationFileNameAsync: a positional pattern stored in the
repo's own `migrationpattern` config field, e.g. `"N00:04T04"` (sequence at
position 0 length 4, title starts at position 4 -- matches a filename like
"0001UsePostgreSQL.md", the exact example from MigrationGuide.md). Only
recognized at all when `migrationpattern` is non-empty and itself parses;
the default, empty `migrationpattern` never matches any file.

**Precedence, mirroring AdrService.ParseFileNameOnly**: try the current
scheme first; only fall back to the legacy scheme if the current scheme
didn't match AND a valid `migrationpattern` is configured.

Known gap (not yet needed by any command that exists so far): the current
scheme's `title` doesn't strip a supersede suffix (a second, doubled
separator followed by the superseded sequence number) -- to close once
Milestone 7's `supersede` command needs it.
"""

import re
from dataclasses import dataclass

_ADR_PATTERN = re.compile(r"^([A-Za-z]*)(\d+)(?:[Vv](\d+)(?:[Rr](\d+))?)?$")
_MIGRATION_PATTERN = re.compile(
    r"^N(\d{2}):(\d{2})T(\d{2})(?:V(\d{2}):(\d{2}))?(?:R(\d{2}):(\d{2}))?(?:P(\d{2}):(\d{2}))?$"
)


@dataclass
class ParsedFileName:
    number: int
    version: int
    revision: int | None
    prefix: str | None = None
    title: str | None = None


def parse_filename(filename, config):
    """Current scheme only. Declares (Fase 6 checklist): recognizes ONLY the
    current scheme -- pair with `parse_legacy_filename` (or use
    `parse_any_filename`) wherever a legacy file must also be considered."""
    if not filename.lower().endswith(".md"):
        return None
    name = filename[:-3]

    index = name.find(config.separator)
    if index < 0:
        return None
    head = name[:index]
    title = name[index + len(config.separator) :]

    match = _ADR_PATTERN.match(head)
    if match is None:
        return None

    return ParsedFileName(
        number=int(match.group(2)),
        version=int(match.group(3)) if match.group(3) else 0,
        revision=int(match.group(4)) if match.group(4) else None,
        prefix=match.group(1) or None,
        title=title,
    )


def parse_migration_pattern(pattern_text):
    """Ported from PatternParser.ParseMigratePattern. Returns a dict mapping
    "N"/"T"/"V"/"R"/"P" to (position, length) -- "T" has no length component
    (its title always runs to the end of the filename), so its length is
    always 0. "N" and "T" are always present when the pattern parses; "V",
    "R", "P" are present only when the pattern text included them."""
    if not pattern_text:
        return None
    match = _MIGRATION_PATTERN.match(pattern_text)
    if match is None:
        return None

    result = {
        "N": (int(match.group(1)), int(match.group(2))),
        "T": (int(match.group(3)), 0),
    }
    if match.group(4) is not None:
        result["V"] = (int(match.group(4)), int(match.group(5)))
    if match.group(6) is not None:
        result["R"] = (int(match.group(6)), int(match.group(7)))
    if match.group(8) is not None:
        result["P"] = (int(match.group(8)), int(match.group(9)))
    return result


def parse_legacy_filename(filename, config):
    """Legacy scheme only. Declares (Fase 6 checklist): recognizes ONLY the
    legacy scheme, and only when `config.migrationpattern` itself parses --
    pair with `parse_filename` (or use `parse_any_filename`) wherever a
    current-scheme file must also be considered."""
    if not filename.lower().endswith(".md"):
        return None
    pattern = parse_migration_pattern(config.migrationpattern)
    if pattern is None:
        return None

    name = filename[:-3]
    n_pos, n_len = pattern["N"]
    t_pos, _ = pattern["T"]
    if len(name) < n_pos + n_len or len(name) < t_pos:
        return None

    seq_text = name[n_pos : n_pos + n_len]
    if not seq_text.isdigit():
        return None
    number = int(seq_text)

    version = 0
    if "V" in pattern:
        v_pos, v_len = pattern["V"]
        if len(name) < v_pos + v_len:
            return None
        version_text = name[v_pos : v_pos + v_len]
        if not version_text.isdigit():
            return None
        version = int(version_text)

    revision = 0
    if "R" in pattern:
        r_pos, r_len = pattern["R"]
        if len(name) < r_pos + r_len:
            return None
        revision_text = name[r_pos : r_pos + r_len]
        if not revision_text.isdigit():
            return None
        revision = int(revision_text)

    prefix = None
    if "P" in pattern:
        p_pos, p_len = pattern["P"]
        if len(name) < p_pos + p_len:
            return None
        prefix = name[p_pos : p_pos + p_len]

    title = name[t_pos:] if t_pos < len(name) else ""

    return ParsedFileName(number=number, version=version, revision=revision, prefix=prefix, title=title)


def parse_any_filename(filename, config):
    """Declares (Fase 6 checklist): recognizes BOTH schemes, current first --
    mirrors AdrService.ParseFileNameOnly's real precedence (try the current
    scheme; fall back to legacy only if it didn't match). Returns
    (scheme, ParsedFileName) with scheme in {"current", "legacy"}, or None
    if neither recognizes the file."""
    parsed = parse_filename(filename, config)
    if parsed is not None:
        return "current", parsed

    parsed = parse_legacy_filename(filename, config)
    if parsed is not None:
        return "legacy", parsed

    return None
