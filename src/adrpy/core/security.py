"""Adversarial-input safety checks."""

import os
import re
from pathlib import Path

from adrpy.core.errors import CommandError, FailureCodes


def resolve_within(base_dir, candidate):
    """Resolves `candidate` (relative or absolute) against `base_dir` and
    rejects it if the real path escapes `base_dir` -- real path resolution
    (following `..` and symlinks), never a string-pattern blacklist. Also
    rejects a candidate that collapses onto `base_dir` itself (e.g. '.',
    '   ', or 'x/..') -- every caller (a decisions folder relative to a
    repository, a filename relative to a folder) expects a real entry
    strictly inside `base_dir`, never `base_dir` unchanged. On Windows, a
    whitespace-only or '.'-only path component silently resolves away, so
    `folderadr` could collapse to the repository root itself without ever
    looking like it "escaped". A NUL byte is rejected explicitly, up
    front, rather than relying on the OS/pathlib layer to raise for it --
    that behavior is not consistent across Python versions (confirmed:
    Python 3.13 on Windows no longer raises here at all, silently
    embedding the NUL into the resolved path instead)."""
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


def is_within(base_dir, candidate, *, resolved_base=None):
    """True if `candidate`'s REAL path (following symlinks/junctions) is
    inside `base_dir`'s real path -- used to filter directory-scan results
    (rglob) after the fact, unlike resolve_within, which builds a path and
    raises. `Path.rglob` happily descends into a Windows junction planted
    inside the scanned folder even though `Path.is_symlink()` does NOT
    detect one (confirmed live: this let `migrate` write a real header
    into a file outside the repository, and poisoned `next_number` with
    an unrelated file's own sequence number) -- so every rglob result must
    be re-checked against the real, resolved boundary, not just the root
    that was originally passed to resolve_within. Never raises: a scan
    should silently treat an escaped candidate as outside the repository's
    boundary, not fail the whole scan over it.

    `resolved_base`, when given, is used instead of re-resolving
    `base_dir` (measured re-resolving the
    same, unchanging base directory on every candidate as 91% of
    scan_decisions's own total time in a loop scanning N candidates
    against the same folder). Optional and backward compatible -- omit
    it and this resolves `base_dir` itself, exactly as before."""
    try:
        base = resolved_base if resolved_base is not None else Path(base_dir).resolve()
        return Path(candidate).resolve().is_relative_to(base)
    except (OSError, ValueError):
        return False


def find_unreadable_subdirectories(folder):
    """`Path.rglob` (CPython's own pathlib implementation) silently swallows any
    `OSError` raised while walking a subtree -- a subfolder that becomes
    unreadable mid-scan (an ordinary ACL choice for a team-restricted
    area, something `core/lock.py`'s own module docstring already
    anticipates for a repo organized into per-team/per-domain
    subfolders) makes every `rglob("*.md")` call in this project
    (`scan_decisions`, `explore`, `migrate`'s own scan, `init`'s
    `_max_existing_numbers`) silently return fewer results, or none,
    with no exception and no signal at all.

    `os.walk`'s own `onerror` hook is the one stdlib mechanism that
    surfaces this instead of swallowing it -- used here PURELY for error
    detection; its own file/directory listing is discarded, so every
    caller keeps using `folder.rglob()` unchanged for the actual scan,
    preserving its own junction-following behavior exactly (already
    covered by other tests) rather than risking a traversal-mechanism
    swap changing what gets found.

    Returns a list of the directory paths (as strings) that could not be
    scanned -- empty when nothing was unreadable."""
    folder = Path(folder)
    unreadable = []

    def _on_error(error):
        unreadable.append(getattr(error, "filename", None) or str(error))

    for _dirpath, _dirnames, _filenames in os.walk(folder, onerror=_on_error):
        pass
    return unreadable


def reject_embedded_delimiter(value, field_name):
    """A value destined for a fixed-position cell of the header table (a
    free-text field like title/scope/domain, or a configurable header/status
    label) must never contain a character that could forge an extra row or
    break the table -- rejected outright, never silently stripped or
    escaped. Uses str.splitlines()'s own (deliberately broad) definition of
    a line boundary as the blacklist -- not because those characters are
    real line terminators to the file format (confirmed live they are not,
    see atomic_write.split_real_lines), but because any one of them left
    inside a single-line cell is exactly the same data-hygiene defect as an
    embedded literal '|', '\\n', or '\\r'.

    Also rejects a value that is whitespace-only (non-empty, but blank
    after stripping): a value like `--summary "   "` would otherwise pass
    this check unnoticed and get written verbatim -- a blank-looking
    heading/label with no error and no warning. A literal empty string is
    deliberately NOT rejected here --
    several callers (new/supersede/version's optional domain/scope) use
    `""` as their own established "not provided" sentinel, distinct from
    "provided but blank"; a required field can never reach this function
    with `""` in the first place (`parse_flags` already treats an empty
    flag value as omitted)."""
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
    decision's parenthesized date and, once ADR004V01 writes one, the hidden
    canonical marker. That parser trusts the FIRST '(' and first ')' in the
    cell to bound the date, then searches after it for a marker -- so a
    label containing a well-formed '(date)<!--Status-->' substring forges a
    marker and date the tool never wrote (confirmed live: a repository
    seeded with `statusnew = "(20200101)<!--Rejected-->"` had a decision
    created today read back as Rejected/2020-01-01 instead of
    Proposed/today). Rejected outright, same shape as
    reject_embedded_delimiter's own blacklist -- scoped to just these four
    fields, since no other field is read by this parsing path.

    Also rejects ':' (a round-27 finding): the Superseded row's own
    successor-reference suffix parsing (`superseded_text.find(":")`,
    core/header.py) finds the FIRST colon anywhere in the cell, not
    necessarily the real one the tool itself writes after the marker --
    a statussup label containing its own ':' wins instead, corrupting
    `superseded_by_file` into the whole cell remainder (confirmed live:
    a statussup of 'Status: Superseded' made `reject` fail with
    superseded-predecessor-not-found on a successor whose primary write
    had already committed)."""
    for forbidden in ("(", ")", "<!--", "-->", ":"):
        if forbidden in value:
            raise CommandError(
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
                f"Field '{field_name}' cannot contain '(', ')', '<!--', '-->', or ':'.",
            )


_FILENAME_UNSAFE_CHARACTERS = frozenset('<>:"/\\|?*')


def reject_filesystem_unsafe_title(value, field_name):
    """`title` only -- unlike every other free-text field, it lands inside
    an actual filename component (naming.build_filename), not just a
    header-table cell, so reject_embedded_delimiter's own blacklist (built
    for a table cell) is not enough. ':' is the sharpest case: it is not
    an invalid Windows filename character, it is the NTFS Alternate-Data-
    Stream separator, so the write of the temp file SUCCEEDS -- only the
    final rename to the real (also colon-containing) name fails, and the
    error-path cleanup only removes the named stream it just wrote,
    leaving the base file NTFS auto-created as a permanent, 0-byte,
    un-cleanable orphan (confirmed live: cleanup_orphaned_temp_files only
    globs '*.tmp', which this leftover's name never matches, and it lacks
    '.md' too, so scan_decisions/explore never see it either -- silent,
    unbounded repository pollution across repeated calls). The other
    Windows-reserved characters (`<>"*?`) fail atomically with no
    leftover, but are rejected here anyway for the same reason `/`/`\\`
    are: this project declares itself OS-independent (pyproject.toml),
    and every one of these is an unremarkable, legal filename byte on a
    POSIX host, where `build_filename`'s output is used exactly the same
    way. Control characters (below 0x20) are rejected outright too, the
    same reasoning as reject_embedded_delimiter's own line-break check."""
    for char in value:
        if char in _FILENAME_UNSAFE_CHARACTERS or ord(char) < 0x20:
            raise CommandError(
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
                f"Field '{field_name}' cannot contain a filesystem-unsafe character "
                f"({''.join(sorted(_FILENAME_UNSAFE_CHARACTERS))!r} or a control character).",
            )


_NO_WORD_CONTENT_PATTERN = re.compile(r"[\s_-]+")


def reject_title_with_no_case_transform_content(value, field_name):
    """`title` only -- `to_case` (core/casing.py) word-splits on
    whitespace/'_'/'-' and falls back to echoing its RAW input unchanged
    when that split finds nothing left to transform, which happens
    exactly when the value consists entirely of those same
    whitespace/'_'/'-' characters. That raw echo lands in
    naming.build_filename verbatim and can collide with the filename's
    own separator -- confirmed live: a title of '-' with the default '-'
    separator produced 'ADR001V01--.md', which naming.parse_filename can
    no longer recognize at all (permanently unreachable by every other
    command: approve/reject/undo/supersede/version/revise all fail
    filename-not-recognized), and its own sequence number was silently
    reallocated to the very next decision created, duplicating it across
    two different files. Rejected outright -- the same class of problem
    as a blank title (reject_embedded_delimiter's own check). Unlike
    that check, this one does NOT exempt a literal empty string: title
    is never an optional/sentinel field anywhere this function is
    called (new/version/revise/supersede/migrate all require a real
    title), and `to_case("")` degenerates the exact same way as a
    whitespace/'_'/'-'-only title does -- a round-27 finding, confirmed
    live: migrate's own title (parse_legacy_filename can genuinely
    return "" for a legacy filename with no title segment) slipped
    through the old `if value and ...` guard, then a later `supersede`
    on that migrated file produced an unrecognizable filename with no
    error and no warning."""
    if not _NO_WORD_CONTENT_PATTERN.sub("", value):
        raise CommandError(
            FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
            f"Field '{field_name}' must contain at least one character other than whitespace, '_', or '-'.",
        )


def reject_marker_comment_syntax(value, field_name):
    """headertablefields/headertablevalues only -- parse_header's own
    is_migrated detection (core/header.py) is pure substring matching
    for an HTML-comment-shaped tail on the table-fields row this pair of
    fields builds (`lines[1].rstrip().endswith(' -->|') and '<!-- ' in
    lines[1]`). A round-27 finding, confirmed live: a hostile config
    setting headertablevalues to e.g. 'Values <!-- x -->' made
    is_migrated=True on the header of every ordinary, non-migrated file
    ever written under that config -- that flag feeds
    counts_as_family_member and several lifecycle eligibility
    exceptions. Rejected outright -- narrower than
    reject_status_marker_forgery_characters (which also blocks '('/')'),
    since neither is part of THIS specific detection's own grammar; a
    legitimate label containing '(' has no bearing on is_migrated and
    must still be accepted."""
    for forbidden in ("<!--", "-->"):
        if forbidden in value:
            raise CommandError(
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER,
                f"Field '{field_name}' cannot contain '<!--' or '-->'.",
            )
