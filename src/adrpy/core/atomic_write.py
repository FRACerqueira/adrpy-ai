"""Atomic file writes shared by every writer in the project, and the
host line-ending helpers they use.

The write functions are thin wrappers over core/fs.py's prepare_write/
commit_write: a temp file in the same directory, then an atomic move --
never truncate-in-place, so a reader can never observe an empty or
partially-written file.
"""

import os
import re

from adrpy.core.fs import write_prepared

# Shared by every reader that streams file content in fixed-size pieces
# instead of loading it whole (core/lifecycle.py's body streaming,
# cli/migrate.py's candidate streaming) -- one chunk-size decision instead
# of two independently-chosen, coincidentally-equal copies.
STREAM_CHUNK_SIZE = 65536

_REAL_NEWLINE = re.compile(r"\r\n|\r|\n")


def split_real_lines(text):
    """Splits `text` on real line terminators only -- CRLF, lone CR, lone
    LF -- unlike `str.splitlines()`, which also treats several Unicode
    line-separator characters (vertical tab, form feed, FS/GS/RS, NEL,
    LINE/PARAGRAPH SEPARATOR) as breaks. A decision body containing any of
    those mid-line must survive `approve` byte-for-byte, same line count
    before and after -- none of them is a real line break here. Using
    `str.splitlines()` for this would silently corrupt such a body into
    extra CRLF lines.

    Matches str.splitlines()'s own convention of never producing a
    trailing empty element for a trailing terminator (only `re.split`'s
    raw behavior would)."""
    if text == "":
        return []
    parts = _REAL_NEWLINE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts


def normalize_newlines(text):
    """Splits `text` on ANY real newline convention already present (bare
    "\\n", "\\r\\n", lone "\\r" -- including a different OS's own
    convention) and rejoins using THIS host's `os.linesep`, discarding
    whatever terminator the source had. Makes every write's newline
    handling the same single call, regardless of whether the content came
    in already terminated, with bare "\\n", or mixed -- the exact ambiguity
    that caused a real doubled-CR bug in the `new` command."""
    if not text:
        return text
    trailing = text[-1] in ("\n", "\r")
    normalized = os.linesep.join(split_real_lines(text))
    if trailing:
        normalized += os.linesep
    return normalized


# The single source of truth for "what does a line terminator look like on
# this host" at the byte level -- every generated-file writer that works in
# bytes (not text) reuses this constant instead of computing its own
# os.linesep.encode() copy.
LINESEP_BYTES = os.linesep.encode("ascii")


def join_lines_with_trailing_terminator(lines):
    """Joins `lines` with THIS host's own os.linesep, always ensuring
    exactly one trailing terminator when there's any content at all --
    the "list of lines back to file content" shape build_header
    (core/header.py) uses, so the host-OS line-ending decision lives in
    one place. Distinct from
    normalize_newlines above, which normalizes already-joined text and
    only adds a trailing terminator when the SOURCE text already had
    one; this always adds one for a non-empty `lines`, matching how a
    header/body is reconstructed from a list of logical lines. Empty
    input returns "" -- no synthetic terminator for genuinely empty
    content."""
    if not lines:
        return ""
    return os.linesep.join(lines) + os.linesep


def atomic_write_text(path, content, exclusive=False):
    """Returns the number of attempts the underlying write actually took
    (see atomic_write_bytes) -- 1 in the overwhelming majority of calls,
    >1 only after absorbing transient contention. Callers that want to
    surface this as a warning (observability) check the return value;
    callers that don't care can simply ignore it. `exclusive` as in
    core/fs.commit_write: FileExistsError if `path` already exists."""
    return atomic_write_bytes(path, normalize_newlines(content).encode("utf-8"), exclusive=exclusive)


def atomic_write_bytes(path, content_bytes, exclusive=False):
    """Same atomicity guarantees as atomic_write_text, but no newline
    normalization at all -- for the one real case where that would be
    wrong: `migrate` prepends a header to an existing file's content
    verbatim, whatever line endings it already has -- confirmed the real
    tool doesn't normalize an already-read string either, so a
    hand-written LF file ends up with a CRLF header pasted onto an
    untouched LF body -- mixed endings in one file, by design, not a bug
    to "fix" by normalizing.

    core/fs.prepare_write then core/fs.commit_write: each retries only a
    transient PermissionError, and any failure removes the temp file."""
    return write_prepared(path, content_bytes, exclusive=exclusive)


def atomic_write_chunks(path, chunks_factory, exclusive=False):
    """Same atomicity guarantees as atomic_write_bytes, but streams content
    from `chunks_factory()` -- a zero-arg callable returning a fresh
    iterable of bytes chunks -- instead of requiring the whole content
    already assembled in memory (ADR006V01: a decision's body, or a
    legacy file's own content during `migrate`, has no schema-imposed
    size bound the way header content does).

    `chunks_factory` is called again only when writing the temp file
    retries (a transient PermissionError on the source read or the temp
    write), never reused across those attempts; a retry of the commit
    reuses the complete temp file and does not call it again."""
    return write_prepared(path, chunks_factory, exclusive=exclusive)
