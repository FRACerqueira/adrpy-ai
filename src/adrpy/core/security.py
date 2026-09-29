"""Adversarial-input safety checks."""

import re
from pathlib import Path

from adrpy.core.errors import CommandError, FailureCodes


def resolve_within(base_dir, candidate):
    """Resolves `candidate` (relative or absolute) against `base_dir` and
    rejects it if the real path (following `..` and symlinks, never a
    string-pattern blacklist) escapes `base_dir`, or collapses onto
    `base_dir` itself (e.g. '.', '   ', or 'x/..'): every caller expects an
    entry strictly inside it. On Windows a whitespace-only or '.'-only
    path component silently resolves away, so `folderadr` could collapse
    to the repository root without looking like it escaped. A NUL byte is
    rejected up front: the OS/pathlib layer does not reject it
    consistently across Python versions (Python 3.13 on Windows silently
    embeds it in the resolved path)."""
    if "\x00" in str(candidate):
        raise CommandError(FailureCodes.PATH_INVALID, f"'{candidate}' is not a usable path.")
    base = Path(base_dir).resolve()
    try:
        resolved = (base / candidate).resolve()
    except (OSError, ValueError) as error:
        raise CommandError(FailureCodes.PATH_INVALID, f"'{candidate}' is not a usable path.") from error
    if not resolved.is_relative_to(base) or resolved == base:
        raise CommandError(
            FailureCodes.PATH_OUTSIDE_REPOSITORY,
            f"'{candidate}' does not resolve to a location strictly inside the repository.",
        )
    return resolved


def reject_aliased_repo_folders(target, config):
    """The real-filesystem counterpart to core/config.py's folderadr/
    folderlog containment guard, which runs on the config text alone and
    so cannot see a junction or symlink inside the repository making two
    unrelated strings (e.g. 'doc/adr' and 'doc/other') alias one real
    directory. A hostile repository can ship both; `new` and `log` would
    then collide on one physical directory.

    Called wherever `folderadr` and `folderlog` are BOTH about to be used
    for real (folder creation at `init`, a folderadr/folderlog change at
    `config`, and `log`). Compares the RESOLVED paths in both directions
    (equal, or either nested inside the other): a junction to a PARENT of
    the other folder aliases just as destructively."""
    folderadr_resolved = resolve_within(target, config.folderadr)
    folderlog_resolved = resolve_within(target, config.folderlog)
    if folderadr_resolved == folderlog_resolved or folderadr_resolved.is_relative_to(
        folderlog_resolved
    ) or folderlog_resolved.is_relative_to(folderadr_resolved):
        raise CommandError(
            FailureCodes.FOLDERADR_FOLDERLOG_ALIAS_SAME_DIRECTORY,
            f"folderadr ('{config.folderadr}') and folderlog ('{config.folderlog}') resolve to the same "
            "real directory (or one nested inside the other) -- likely a symlink or junction planted "
            "inside the repository, not just a coincidentally-similar configured path.",
        )


def is_within(base_dir, candidate, *, resolved_base=None):
    """True if `candidate`'s REAL path (following symlinks/junctions) is
    inside `base_dir`'s real path -- for checking an existing path (the
    --file target, the skills installer's paths), unlike resolve_within,
    which builds a path and raises. A path through a Windows junction
    inside `base_dir` can resolve outside it, and `Path.is_symlink()` does
    NOT detect a junction. Never raises: an unresolvable candidate counts
    as outside.

    `resolved_base`, when given, is used instead of re-resolving
    `base_dir` (re-resolving the same, unchanging base directory on every
    candidate was measured at 91% of a scan's total time). Omit it and
    this resolves `base_dir` itself."""
    try:
        base = resolved_base if resolved_base is not None else Path(base_dir).resolve()
        return Path(candidate).resolve().is_relative_to(base)
    except (OSError, ValueError):
        return False


def reject_embedded_delimiter(value, field_name):
    """A value destined for a fixed-position cell of the header table (a
    free-text field like title/scope/domain, or a configurable header/status
    label) must never contain a character that could forge an extra row or
    break the table -- rejected outright, never stripped or escaped. The
    blacklist is '|' plus str.splitlines()'s deliberately broad set of line
    boundaries: most are not line terminators to the file format (see
    atomic_write.split_real_lines), but any of them inside a single-line
    cell is the same defect as an embedded '\\n' or '\\r'.

    Also rejects a whitespace-only value (e.g. `--summary "   "`), which
    would otherwise be written verbatim as a blank-looking heading or
    label. A literal empty string is deliberately NOT rejected:
    new/supersede/version use `""` as the "not provided" sentinel for the
    optional domain/scope, and a required field never reaches here with
    `""` (`parse_flags` rejects an empty value unless the flag allows one)."""
    if value != "" and not value.strip():
        raise CommandError(FailureCodes.FIELD_IS_BLANK, f"Field '{field_name}' cannot be blank.")
    if "|" in value or value != "".join(value.splitlines()):
        raise CommandError(
            FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
            f"Field '{field_name}' cannot contain '|' or a line-break-like character.",
        )


def reject_status_marker_forgery_characters(value, field_name):
    """statusnew/statusacc/statusrej/statussup only -- lands verbatim in the
    status cell that _parse_status_cell (core/header.py) also parses for the
    decision's parenthesized date and, once ADR0004V01 writes one, the hidden
    canonical marker. That parser trusts the FIRST '(' and first ')' in the
    cell to bound the date, then searches after it for a marker -- so a
    label containing a well-formed '(date)<!--Status-->' substring forges a
    marker and date the tool never wrote (e.g. a repository seeded with
    `statusnew = "(20200101)<!--Rejected-->"` has a decision created today
    read back as Rejected/2020-01-01 instead of Proposed/today). Rejected outright, same shape as
    reject_embedded_delimiter's own blacklist -- scoped to just these four
    fields, since no other field is read by this parsing path.

    Also rejects ':': the Superseded row's own
    successor-reference suffix parsing (`superseded_text.find(":")`,
    core/header.py) finds the FIRST colon anywhere in the cell, not
    necessarily the real one the tool itself writes after the marker --
    a statussup label containing its own ':' wins instead, corrupting
    `superseded_by_file` into the whole cell remainder (e.g. with a
    statussup of 'Status: Superseded')."""
    for forbidden in ("(", ")", "<!--", "-->", ":"):
        if forbidden in value:
            raise CommandError(
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
                f"Field '{field_name}' cannot contain '(', ')', '<!--', '-->', or ':'.",
            )


_FILENAME_UNSAFE_CHARACTERS = frozenset('<>:"/\\|?*')


def reject_filesystem_unsafe_title(value, field_name):
    """`title` only -- it lands inside a filename component
    (naming.build_filename), not just a header-table cell, so
    reject_embedded_delimiter's blacklist is not enough. ':' is the
    sharpest case: on NTFS it is the Alternate-Data-Stream separator, so
    the temp write SUCCEEDS and only the final rename fails; the cleanup
    removes the stream it wrote and leaves the base file NTFS auto-created
    as a permanent 0-byte orphan that no sweep or scan ever sees (its name
    is neither this tool's '*.tmp' nor '.md'). The other Windows-reserved
    characters (`<>"*?`) fail atomically with no leftover, but are
    rejected anyway, as `/` and `\\` are: the project is OS-independent
    (pyproject.toml), and each is a legal filename byte on POSIX. Control
    characters (below 0x20) are rejected for the same reason as
    reject_embedded_delimiter's line-break check."""
    for char in value:
        if char in _FILENAME_UNSAFE_CHARACTERS or ord(char) < 0x20:
            raise CommandError(
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
                f"Field '{field_name}' cannot contain a filesystem-unsafe character "
                f"({''.join(sorted(_FILENAME_UNSAFE_CHARACTERS))!r} or a control character).",
            )


_NO_WORD_CONTENT_PATTERN = re.compile(r"[\s_-]+")


def reject_title_with_no_case_transform_content(value, field_name):
    """`title` only -- `to_case` (core/casing.py) returns its RAW input when
    splitting on whitespace/'_'/'-' leaves no words, i.e. when the value
    consists only of those characters. That raw echo lands in
    naming.build_filename verbatim and can collide with the separator: a
    title of '-' with the default '-' separator produces
    'ADR0001V01--.md', which naming.parse_filename cannot recognize (every
    other command then fails filename-not-recognized), and whose number
    would be reallocated to the next decision. Unlike
    reject_embedded_delimiter's blank check, a literal empty string is
    rejected too: no caller treats title as optional, and migrate's title
    can be "" (parse_legacy_filename on a legacy name with no title
    segment), which a later `supersede` would turn into an unrecognizable
    filename with no error."""
    if not _NO_WORD_CONTENT_PATTERN.sub("", value):
        raise CommandError(
            FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
            f"Field '{field_name}' must contain at least one character other than whitespace, '_', or '-'.",
        )


def reject_marker_comment_syntax(value, field_name):
    """headertablefields/headertablevalues only -- parse_header's
    is_migrated detection (core/header.py) is pure substring matching for
    an HTML-comment-shaped tail on the table-fields row these fields build
    (`lines[1].rstrip().endswith(' -->|') and '<!-- ' in lines[1]`). A
    hostile config setting headertablevalues to e.g. 'Values <!-- x -->'
    makes is_migrated=True on every ordinary header written under it, and
    that flag feeds several lifecycle eligibility exceptions. Narrower
    than reject_status_marker_forgery_characters: '(' and ')' are not part
    of this detection, so a label containing them must still be accepted."""
    for forbidden in ("<!--", "-->"):
        if forbidden in value:
            raise CommandError(
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
                f"Field '{field_name}' cannot contain '<!--' or '-->'.",
            )
