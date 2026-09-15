"""Atomic file writes shared by every writer in the project (harness Fase 4).

Every write goes through a temp file in the same directory, then an atomic
`os.replace` -- never truncate-in-place, so a concurrent reader can never
observe an empty or partially-written file. A short, limited retry absorbs
a transient permission failure (e.g. a Windows "pending delete" state under
a concurrent reader); anything past that surfaces as a real error.
"""

import os
import time
import uuid
from pathlib import Path

RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.05
ORPHAN_MAX_AGE_SECONDS = 30


def normalize_newlines(text):
    """Splits `text` on ANY newline convention already present (bare "\\n",
    "\\r\\n", lone "\\r" -- including a different OS's own convention) and
    rejoins using THIS host's `os.linesep`. Not a Python-side invention --
    mirrors what AdrPlus itself does when carrying body content forward
    between operations (AdrService.cs:413: split into lines, then
    `string.Join(Environment.NewLine, ...)`, discarding whatever terminator
    the source had). Makes every write's newline handling the same single
    call, regardless of whether the content came in already terminated,
    with bare "\\n", or mixed -- the exact ambiguity that caused a real
    doubled-CR bug in the `new` command (see that commit)."""
    if not text:
        return text
    trailing = text[-1] in ("\n", "\r")
    normalized = os.linesep.join(text.splitlines())
    if trailing:
        normalized += os.linesep
    return normalized


def atomic_write_text(path, content):
    atomic_write_bytes(path, normalize_newlines(content).encode("utf-8"))


def atomic_write_bytes(path, content_bytes):
    """Same atomicity/retry guarantees as atomic_write_text, but no newline
    normalization at all -- for the one real case where that would be
    wrong: `migrate` prepends a header to an existing file's content
    verbatim, whatever line endings it already has (confirmed against a
    real `adrplus migrate` run: the original's own text encoding doesn't
    normalize an already-read string either, so a hand-written LF file
    ends up with a CRLF header pasted onto an untouched LF body -- mixed
    endings in one file, by design, not a bug to "fix" by normalizing)."""
    path = Path(path)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    last_error = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            with open(temp_path, "wb") as handle:
                handle.write(content_bytes)
            os.replace(temp_path, path)
            return
        except PermissionError as error:
            last_error = error
            temp_path.unlink(missing_ok=True)
            time.sleep(RETRY_DELAY_SECONDS)
    raise last_error


def cleanup_orphaned_temp_files(directory, max_age_seconds=ORPHAN_MAX_AGE_SECONDS):
    """Removes leftover `*.tmp` files (from a write interrupted by something
    other than the transient permission failure retried above -- a killed
    process, a full disk) once older than `max_age_seconds`. Returns the
    paths removed, so the caller can warn about it (Fase 4: "com aviso
    quando algo é de fato removido")."""
    directory = Path(directory)
    now = time.time()
    removed = []
    for candidate in directory.glob("*.tmp"):
        try:
            age = now - candidate.stat().st_mtime
        except FileNotFoundError:
            continue
        if age > max_age_seconds:
            candidate.unlink(missing_ok=True)
            removed.append(candidate)
    return removed
