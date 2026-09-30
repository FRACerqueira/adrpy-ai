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
# instead of loading it whole (core/lifecycle.py, cli/migrate.py).
STREAM_CHUNK_SIZE = 65536

_REAL_NEWLINE = re.compile(r"\r\n|\r|\n")


def split_real_lines(text):
    """Splits `text` on real line terminators only -- CRLF, lone CR, lone
    LF. `str.splitlines()` also breaks on vertical tab, form feed,
    FS/GS/RS, NEL and LINE/PARAGRAPH SEPARATOR, which would corrupt a
    decision body holding one mid-line into extra lines; such a body must
    survive `approve` byte for byte.

    Like str.splitlines(), a trailing terminator yields no trailing empty
    element."""
    if text == "":
        return []
    parts = _REAL_NEWLINE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts


def normalize_newlines(text):
    """Rejoins `text`'s lines with THIS host's `os.linesep`, whatever
    terminators it came with (bare "\\n", "\\r\\n", lone "\\r", or a mix);
    a trailing terminator is kept only when the source had one. Every
    write goes through this one call, so content that arrives already
    CRLF-terminated never gets a doubled CR."""
    if not text:
        return text
    trailing = text[-1] in ("\n", "\r")
    normalized = os.linesep.join(split_real_lines(text))
    if trailing:
        normalized += os.linesep
    return normalized


LINESEP_BYTES = os.linesep.encode("ascii")


def join_lines_with_trailing_terminator(lines):
    """Joins `lines` with THIS host's os.linesep plus exactly one trailing
    terminator -- how build_header (core/header.py) turns logical lines
    back into file content. Unlike normalize_newlines, the terminator is
    added whether or not the source had one. Empty `lines` returns ""."""
    if not lines:
        return ""
    return os.linesep.join(lines) + os.linesep


def atomic_write_text(path, content, exclusive=False):
    """Returns the number of attempts the underlying write took (see
    atomic_write_bytes): 1 unless transient contention was absorbed; a
    caller may surface more as a warning. `exclusive` as in
    core/fs.commit_write: FileExistsError if `path` already exists."""
    return atomic_write_bytes(path, normalize_newlines(content).encode("utf-8"), exclusive=exclusive)


def atomic_write_bytes(path, content_bytes, exclusive=False):
    """Same atomicity guarantees as atomic_write_text, but no newline
    normalization at all -- for `migrate`, which prepends a header to an
    existing file's content verbatim, whatever line endings it has, as
    the real tool does: a hand-written LF file ends up with a CRLF header
    on an untouched LF body. Mixed endings in one file are by design, not
    a bug to "fix" by normalizing.

    core/fs.prepare_write then core/fs.commit_write: each retries only a
    transient PermissionError, and any failure removes the temp file."""
    return write_prepared(path, content_bytes, exclusive=exclusive)


def atomic_write_chunks(path, chunks_factory, exclusive=False):
    """Same atomicity guarantees as atomic_write_bytes, but streams content
    from `chunks_factory()` -- a zero-arg callable returning a fresh
    iterable of bytes chunks -- instead of requiring the whole content
    already assembled in memory (ADR0006V01: a decision's body, or a
    legacy file's own content during `migrate`, has no schema-imposed
    size bound the way header content does).

    `chunks_factory` is called again only when writing the temp file
    retries (a transient PermissionError on the source read or the temp
    write), never reused across those attempts; a retry of the commit
    reuses the complete temp file and does not call it again."""
    return write_prepared(path, chunks_factory, exclusive=exclusive)
