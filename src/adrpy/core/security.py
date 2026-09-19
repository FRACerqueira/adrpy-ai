"""Adversarial-input safety checks."""

import os
from pathlib import Path

from adrpy.core.errors import CommandError


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
    looking like it "escaped"."""
    base = Path(base_dir).resolve()
    try:
        resolved = (base / candidate).resolve()
    except (OSError, ValueError) as error:
        raise CommandError("path-invalid", f"'{candidate}' is not a usable path.") from error
    if not resolved.is_relative_to(base) or resolved == base:
        raise CommandError(
            "path-outside-repository",
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
        raise CommandError("field-is-blank", f"Field '{field_name}' cannot be blank.")
    if "|" in value or value != "".join(value.splitlines()):
        raise CommandError(
            "field-contains-forbidden-character",
            f"Field '{field_name}' cannot contain '|' or a line-break-like character.",
        )
