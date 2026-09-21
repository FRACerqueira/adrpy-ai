"""Filename parsing for both naming schemes.

**Current scheme** -- `^([A-Za-z]*)(\\d+)(?:[Vv](\\d+)(?:[Rr](\\d+))?)?$`:
number/version/revision are variable-length digit runs, NOT padded to the
config's lenseq/lenversion/lenrevision -- deliberately so, since a file
whose digits no longer fit a newly-*shrunk* config must still be
recognized (needed by `init`'s digit-overflow check).

**Legacy scheme** -- a positional pattern stored in the repo's own
`migrationpattern` config field, e.g. `"N00:04T04"` (sequence at position
0 length 4, title starts at position 4 -- matches a filename like
"0001UsePostgreSQL.md"). Only recognized at all when `migrationpattern`
is non-empty and itself parses; the default, empty `migrationpattern`
never matches any file.

**Precedence**: try the current scheme first; only fall back to the
legacy scheme if the current scheme didn't match AND a valid
`migrationpattern` is configured.
"""

import re
from dataclasses import dataclass

from adrpy.core.casing import to_case
from adrpy.core.errors import CommandError, FailureCodes

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
    superseded_from: int | None = None


def parse_filename(filename, config):
    """Current scheme only. Recognizes ONLY the current scheme -- pair
    with `parse_legacy_filename` (or use
    `parse_any_filename`) wherever a legacy file must also be considered.

    The supersede suffix (a doubled separator followed by the superseded
    sequence number) is split off BEFORE looking for the single-separator
    boundary between the prefix+numbers segment and the title, so it
    never leaks into `title`."""
    if not filename.lower().endswith(".md"):
        return None
    name = filename[:-3]

    double_separator = config.separator * 2
    supersede_parts = name.split(double_separator)
    if len(supersede_parts) > 2:
        return None
    superseded_from = None
    if len(supersede_parts) == 2:
        suffix = supersede_parts[1]
        if not suffix.isdigit():
            return None
        superseded_from = int(suffix)
    name = supersede_parts[0]

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
        superseded_from=superseded_from,
    )


def parse_migration_pattern(pattern_text):
    """Returns a dict mapping "N"/"T"/"V"/"R"/"P" to (position, length) --
    "T" has no length component
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
    """Legacy scheme only. Recognizes ONLY the legacy scheme, and only
    when `config.migrationpattern` itself parses --
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
    """Recognizes BOTH schemes, current first: try the current scheme;
    fall back to legacy only if it didn't match. Returns
    (scheme, ParsedFileName) with scheme in {"current", "legacy"}, or None
    if neither recognizes the file."""
    parsed = parse_filename(filename, config)
    if parsed is not None:
        return "current", parsed

    parsed = parse_legacy_filename(filename, config)
    if parsed is not None:
        return "legacy", parsed

    return None


def build_filename(config, record):
    """The supersede suffix is unconditional -- never a
    collision-disambiguator."""
    base = f"{config.prefix or ''}{record.number:0{config.lenseq}d}"
    version_part = f"V{record.version:0{config.lenversion}d}"
    revision_part = f"R{record.revision:0{config.lenrevision}d}" if config.lenrevision > 0 else ""
    title_part = to_case(record.title, config.casetransform)
    supersede_part = (
        f"{config.separator}{config.separator}{record.superseded:0{config.lenseq}d}"
        if record.superseded
        else ""
    )
    filename = f"{base}{version_part}{revision_part}{config.separator}{title_part}{supersede_part}.md"

    # A round-27 security finding: title, once case-transformed, can
    # collide with this filename's own separator-delimited grammar in
    # ways no single character blacklist has fully enumerated -- three
    # distinct collision shapes were found and fixed this session alone
    # (a title made entirely of separator-like characters; an empty
    # title, reachable only through migrate; and a title containing the
    # CONFIGURED separator itself, e.g. a leading '.' when separator is
    # '.'). Rather than a fourth narrow guard for the next shape nobody's
    # found yet, this re-parses its own output and refuses to return a
    # filename that doesn't round-trip back to exactly the identity just
    # encoded -- closes the whole class, not just the instances already
    # found. Checks number/version/revision/superseded_from specifically
    # (not the title text itself, which parse_filename never needs to
    # match exactly -- a title with a separator character safely in its
    # MIDDLE, e.g. "v1.2.3" with separator=".", still round-trips fine;
    # only a collision at the number/title BOUNDARY actually breaks
    # anything).
    reparsed = parse_filename(filename, config)
    if (
        reparsed is None
        or reparsed.number != record.number
        or reparsed.version != record.version
        or reparsed.revision != record.revision
        or reparsed.superseded_from != record.superseded
    ):
        raise CommandError(
            FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME,
            f"Cannot use this title: the resulting filename ('{filename}') would not be recognized as "
            "this same decision when read back, which would permanently orphan it.",
            data={"filename": filename},
        )
    return filename
