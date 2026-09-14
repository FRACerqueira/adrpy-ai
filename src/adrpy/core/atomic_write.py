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


def atomic_write_text(path, content, newline):
    path = Path(path)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    last_error = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            with open(temp_path, "w", encoding="utf-8", newline=newline) as handle:
                handle.write(content)
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
