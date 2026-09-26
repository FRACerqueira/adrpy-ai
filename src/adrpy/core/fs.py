"""The file I/O primitives every other module goes through: bounded and
retried reads, deletes, and the two-step write -- `prepare_write` puts
the complete content in a temp file next to the target, `commit_write`
moves it into place. Nothing else in src/adrpy calls Path.read_bytes/
read_text/write_bytes/write_text/unlink or os.replace/os.remove directly
(tests/test_fs.py enforces it).

A write never truncates in place: a reader sees the old file or the new
one, never a partial one. A short retry absorbs a transient
PermissionError (a Windows "pending delete"/sharing-violation window);
any other OSError fails at once. A crash between the two steps leaves at
most a temp file, which `cleanup_orphaned_temp_files` removes later.
"""

import errno
import glob
import hashlib
import os
import re
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# Write side: exponential backoff (a flat 3x50ms window was empirically
# only ~68% reliable under an aggressive concurrent reader).
RETRY_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 0.05
# Read side: the lighter case, flat delay.
READ_RETRY_ATTEMPTS = 3
READ_RETRY_DELAY_SECONDS = 0.05
ORPHAN_MAX_AGE_SECONDS = 30

# Which exclusive-create branch commit_write takes. A module constant so a
# test can run the other OS's branch.
_IS_WINDOWS = os.name == "nt"
# Whether scan_tree checks an entry's reparse-point attribute (Windows
# only) -- its own constant, so flipping the one above never turns off
# junction detection.
_HAS_REPARSE_POINTS = os.name == "nt"

# prepare_write names its temp file `<target name>.<16 hex>.tmp` (16 of a
# uuid4's hex digits; earlier builds used all 32); the orphan sweeps below
# match only those exact shapes, so no other *.tmp a user keeps in the
# same folder is ever mistaken for one of these. The folder sweep also
# needs a `.md` target name: this tool writes nothing else in the
# decisions and decision-log folders.
_OWN_TEMP_SUFFIX = r"\.(?:[0-9a-f]{16}|[0-9a-f]{32})\.tmp"
_OWN_TEMP_NAME = re.compile(r".+\.md" + _OWN_TEMP_SUFFIX)

# The longest name this tool writes: one name's limit on NTFS, ext4 and
# APFS (255, counted in UTF-8 bytes, which are never fewer than NTFS's
# UTF-16 units), less the suffix of the temp file written next to it.
MAX_NAME_BYTES = 255 - len(".0123456789abcdef.tmp")


def retry_on_permission(fn, *, attempts, delay, exponential=False):
    """Calls the zero-arg `fn`, retrying only a PermissionError, up to
    `attempts` calls in total, sleeping `delay` between them (doubled
    after each failure when `exponential`). Any other exception
    propagates on the first occurrence; the PermissionError itself is
    re-raised once the attempts are spent. Returns (result, calls made)."""
    for attempt in range(attempts):
        try:
            return fn(), attempt + 1
        except PermissionError:
            if attempt >= attempts - 1:
                raise
            time.sleep(delay * (2**attempt) if exponential else delay)


def read_with_permission_retry(read, attempts=READ_RETRY_ATTEMPTS, delay=READ_RETRY_DELAY_SECONDS):
    """The read side's retry: `read()`'s own result, flat delay."""
    return retry_on_permission(read, attempts=attempts, delay=delay)[0]


def read_bounded(path, max_bytes, chunk_size):
    """Reads at most `max_bytes` plus one chunk's worth of overrun -- the
    overrun only tells the caller the real file is larger, and is never
    meant to be used as content. Never the whole file regardless of its
    true size. No retry of its own: callers wrap it."""
    chunks = []
    total = 0
    with Path(path).open("rb") as handle:
        while total <= max_bytes:
            more = handle.read(chunk_size)
            if not more:
                break
            chunks.append(more)
            total += len(more)
    return b"".join(chunks)


def is_zero_bytes(path):
    """True for a 0-byte file, what an interrupted create's reservation
    leaves (a file holding only a BOM is not one). False when it cannot
    be read: the caller's own read reports that."""
    try:
        return os.stat(path).st_size == 0
    except OSError:
        return False


def unlink_with_retry(path):
    """Deletes `path` (already absent is fine), retrying a transient
    PermissionError with the write side's budget and exponential backoff
    -- an editor, an agent or an antivirus scanner briefly holding the
    file (WinError 32) failed adrpy-skills' remove outright (measured: 40
    of 60 removes under 3 concurrent `list` readers, 0 of 60 with this
    retry; the read side's flat budget was too short). Re-raises once
    retries are exhausted: a delete that could not be made is reported."""
    retry_on_permission(
        lambda: Path(path).unlink(missing_ok=True),
        attempts=RETRY_ATTEMPTS,
        delay=RETRY_DELAY_SECONDS,
        exponential=True,
    )


def _discard(temp_path):
    """Best-effort removal of a temp file this module created. A failure
    here never replaces the error that led to it; whatever is left is an
    orphan the next sweep removes. Returns whether the file is gone."""
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class Prepared:
    """A complete temp file waiting to be committed onto `path`, with the
    sha256 `digest` and `size` of the bytes written to it (see
    write_landed)."""

    path: Path
    temp_path: Path
    attempts: int
    digest: bytes
    size: int


def prepare_write(path, data):
    """Writes the complete new content of `path` into a temp file in the
    same folder, leaving `path` itself untouched. `data` is either bytes,
    or a zero-arg callable returning a fresh iterable of bytes chunks
    (for content that is never held in memory whole). A transient
    PermissionError retries the whole temp write, calling the chunk
    factory again from the start; any failure removes the temp file
    before propagating."""
    path = Path(path)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex[:16]}.tmp")

    def _write_temp():
        # A fresh digest per attempt: a retry rewrites the temp from the start.
        digest = hashlib.sha256()
        size = 0
        try:
            with open(temp_path, "wb") as handle:
                for chunk in data() if callable(data) else (data,):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except BaseException:
            _discard(temp_path)
            raise
        return digest.digest(), size

    (digest, size), attempts = retry_on_permission(
        _write_temp, attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY_SECONDS, exponential=True
    )
    return Prepared(path=path, temp_path=temp_path, attempts=attempts, digest=digest, size=size)


def write_landed(prepared):
    """True when `prepared.path` now holds exactly the bytes prepared for
    it. An interrupt (Ctrl+C) can reach Python right after the rename or
    replace that commits a write has returned -- still inside
    commit_write, or before its caller records the write -- so a caller
    that reports what it wrote decides it from the disk: a step counts as
    applied when this is True. The read retries a transient
    PermissionError like every other read. False when the target cannot
    be read (the caller then keeps its "not written" answer)."""

    def matches():
        if Path(prepared.path).stat().st_size != prepared.size:
            return False
        digest = hashlib.sha256()
        with Path(prepared.path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.digest() == prepared.digest

    try:
        return read_with_permission_retry(matches)
    except OSError:
        return False


def landed_after_failure(prepared):
    """write_landed for a handler already reporting a failure (a Ctrl+C
    or an error): a further Ctrl+C during the check leaves this one file
    unconfirmed instead of escaping, so the handler still reports what it
    had counted. Never used outside such a handler, where a Ctrl+C is the
    user's first and must stop the command."""
    try:
        return write_landed(prepared)
    except KeyboardInterrupt:
        return False


def discard_write(prepared):
    """Drops a prepared write that will not be committed."""
    _discard(prepared.temp_path)


_NO_HARD_LINKS = {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS}


def _copy_exclusive(source, target):
    """Fallback for filesystems without hard links (exFAT, FAT, some
    network shares): an empty file created with O_EXCL reserves the name
    (refusing an existing one), then the complete temp replaces it in one
    atomic step. A crash in between leaves at most that empty file (the
    repository validator reports it: no header) and the temp; never a
    truncated decision. A failure before the replace removes the
    reservation, so a retry does not take it for someone else's file;
    when it cannot be removed, a PermissionError (which commit_write
    would retry, into that reservation) becomes an OSError naming it."""
    os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))
    try:
        os.replace(source, target)
    except BaseException as error:
        if not _discard(target) and isinstance(error, PermissionError):
            raise OSError(
                errno.EIO,
                f"the write failed ({error}) and the empty file reserving its name could not be removed; "
                "remove it by hand",
                str(target),
            ) from error
        raise


def commit_write(prepared, exclusive=False):
    """Moves a prepared temp file onto its target, retrying a transient
    PermissionError without rewriting the temp file. Returns the number
    of attempts. On any failure the temp file is removed and the target
    is as it was.

    `exclusive=True` creates the target only if the name is free, and
    raises FileExistsError otherwise, the existing file untouched. On
    Windows that is os.rename, which refuses an existing target; on
    POSIX, where rename would replace it, os.link, which refuses too,
    then the temp name is removed (if that removal fails, the target is
    still created and the temp is an orphan for the next sweep)."""
    source, target = prepared.temp_path, prepared.path

    def _apply():
        if not exclusive:
            os.replace(source, target)
        elif _IS_WINDOWS:
            os.rename(source, target)
        else:
            try:
                os.link(source, target)
            except FileExistsError:
                raise
            except OSError as error:
                if error.errno not in _NO_HARD_LINKS:
                    raise
                _copy_exclusive(source, target)

    try:
        _, attempts = retry_on_permission(
            _apply, attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY_SECONDS, exponential=True
        )
    except BaseException:
        _discard(source)
        raise
    if exclusive and not _IS_WINDOWS:
        _discard(source)
    return attempts


def write_prepared(path, data, exclusive=False):
    """prepare_write then commit_write. Returns the attempts both steps
    took together: 1 when neither retried."""
    prepared = prepare_write(path, data)
    return prepared.attempts + commit_write(prepared, exclusive=exclusive) - 1


def make_dirs(folder):
    """Creates `folder` and its missing parents. Returns the highest
    folder this call created, None when `folder` already existed -- for
    remove_created_dirs. A failure part-way (the parents created, the
    folder itself refused) removes what this call created."""
    folder = Path(folder)
    top = None
    current = folder
    while not current.exists() and current.parent != current:
        top = current
        current = current.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except BaseException:
        remove_created_dirs(folder, top)
        raise
    return top


def remove_created_dirs(folder, top):
    """Undoes make_dirs: removes `folder` and its parents up to `top`,
    bottom-up, stopping at the first one that is not empty (or cannot be
    removed); one that was never created is skipped. Nothing when `top`
    is None."""
    if top is None:
        return
    current = Path(folder)
    while True:
        try:
            current.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            return
        if current == top:
            return
        current = current.parent


@dataclass(frozen=True)
class TreeScan:
    """What scan_tree found under one folder: the `.md` and `.tmp` files
    inside its real boundary, the candidates excluded for escaping it
    (through a junction or a file symlink), and the directories that
    could not be listed."""

    markdown: tuple
    temp: tuple
    excluded: tuple
    unreadable: tuple


def _is_link(entry):
    """A symlink, a junction or (Windows) any other reparse point: an entry
    whose real path may not be its parent's real path plus its name. On
    Windows the attributes come with the directory listing (no extra
    call); an entry that cannot be inspected counts as a link."""
    try:
        if entry.is_symlink():
            return True
        if _HAS_REPARSE_POINTS:
            return bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return False
    except OSError:
        return True


def _real_path(path, known_parent, entry):
    """`path`'s real path: its parent's already-known real path plus its
    name, unless the parent's is unknown (reached through a link) or the
    entry is itself a link -- then resolved. None when it cannot be."""
    if known_parent is not None and not _is_link(entry):
        return known_parent / entry.name
    try:
        return path.resolve()
    except (OSError, ValueError):
        return None


def scan_tree(folder):
    """The one traversal of a folder, os.walk's order (top-down, a
    directory's files before its subdirectories), recording every
    directory it could not list (rglob would skip it silently). Like
    rglob and os.walk, it descends into junctions but not into directory
    symlinks; every file found is kept only if its real path stays inside
    `folder` (the is_within rule), and a file reached twice through a
    junction is kept once; a directory reached again through a junction
    cycle is not listed twice, and a junction to a directory outside
    `folder` is excluded as a whole, not entered. A directory symlink is
    neither entered nor reported in `excluded`, wherever it points. The extension match follows the OS's own case
    rule (os.path.normcase), as rglob's does. A missing `folder` is
    reported as unreadable.

    Only a link is resolved: a file or directory reached from the
    resolved folder through plain directories has the real path of its
    parent plus its own name, so it is inside by construction; a symlink,
    a junction or another reparse point -- and everything reached through
    one -- is resolved and checked."""
    folder = Path(folder)
    try:
        resolved = folder.resolve()
    except (OSError, ValueError):
        resolved = None
    excluded, unreadable = [], []
    # real path -> the path found; a file reached twice (through a junction
    # inside the folder) is kept once, under the path that needs no link.
    found = {".md": {}, ".tmp": {}}

    # (directory, its real path when known without resolving, else None)
    pending = [(folder, resolved)]
    # Real paths already listed: a junction back to a listed directory
    # (a cycle) is not entered again.
    listed = set()
    # Directories entered through a link wait until every plain directory
    # is listed, so a file reachable both ways is kept under its plain path.
    through_links = []
    while pending or through_links:
        directory, real_directory = pending.pop() if pending else through_links.pop(0)
        if real_directory is not None:
            if real_directory in listed:
                continue
            listed.add(real_directory)
        try:
            with os.scandir(os.fspath(directory)) as listing:
                entries = list(listing)
        except OSError as error:
            unreadable.append(getattr(error, "filename", None) or str(error))
            continue
        subdirectories = []
        for entry in entries:
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            if is_dir:
                # os.walk does not descend into a directory symlink.
                if not entry.is_symlink():
                    subdirectories.append(entry)
                continue
            extension = os.path.normcase(entry.name)[-4:]
            kind = ".md" if extension.endswith(".md") else ".tmp" if extension == ".tmp" else None
            if kind is None:
                continue
            candidate = directory / entry.name
            real = _real_path(candidate, real_directory, entry)
            try:
                inside = resolved is not None and real is not None and real.is_relative_to(resolved)
            except ValueError:
                inside = False
            if not inside:
                excluded.append(candidate)
                continue
            known = found[kind].get(real)
            if known is None or os.path.normcase(str(candidate.relative_to(folder))) == os.path.normcase(
                str(real.relative_to(resolved))
            ):
                found[kind][real] = candidate
        # Depth-first, in listing order, as os.walk.
        for entry in reversed(subdirectories):
            path = directory / entry.name
            real_sub = _real_path(path, real_directory, entry)
            try:
                inside = resolved is not None and real_sub is not None and real_sub.is_relative_to(resolved)
            except ValueError:
                inside = False
            if not inside:
                # A link out of the folder is excluded without being
                # entered (a junction to an ancestor would otherwise walk
                # the whole disk).
                excluded.append(path)
                continue
            if _is_link(entry) or real_directory is None:
                through_links.append((path, real_sub))
            else:
                pending.append((path, real_sub))
    return TreeScan(tuple(found[".md"].values()), tuple(found[".tmp"].values()), tuple(excluded), tuple(unreadable))


def cleanup_orphaned_temp_files(directory, max_age_seconds=ORPHAN_MAX_AGE_SECONDS, warnings=None, scan=None):
    """Removes leftover temp files (from a write interrupted by something
    other than the transient permission failure retried above -- a killed
    process, a full disk) once older than `max_age_seconds`. Returns the
    paths removed, so the caller can warn about it.

    Another process could hold a temp file open (or have already removed
    it) at the exact moment this scan reaches it. Best-effort per
    candidate: a transient OSError here does not
    fail the caller's entire command over best-effort housekeeping
    unrelated to what it was actually asked to do -- left in place for a
    later cleanup pass instead, and reported via `warnings` when given.

    Known limitation (decided, not fixed): the 30s age is measured against
    the temp file's own mtime. On a network share whose server clock runs
    well behind this machine's, a concurrent call can sweep another call's
    still-in-flight temp file; that write then fails instead of being
    retried, since the write cannot tell its temp file was swept. The
    failure surfaces as the calling command's own code for that write: an
    io-error for a single-write command, with nothing committed and
    re-running succeeds; for supersede and reject, a failure before their
    first commit (supersede-successor-write-failed, reject-predecessor-
    write-failed) also with nothing committed, and one after it as
    multi-file-write-partially-applied (data.applied/data.pending); and a
    per-file failure in migrate's migration-write-failed, where re-running
    migrates what is left.

    Recursive, not glob -- every other scan in this codebase (scan_tree)
    already covers subfolders under folderadr; a non-recursive scan here would
    leave an orphan inside a subfolder unfound and unreported (a
    housekeeping leak, not a correctness issue -- temp files never
    collide by name and are never read by anything)."""
    # `scan`: the folder's scan_tree when the caller already walked it
    # (its `.tmp` files are already inside the folder's real boundary);
    # otherwise the folder is walked here.
    if scan is None:
        scan = scan_tree(directory)
    candidates = (candidate for candidate in scan.temp if _OWN_TEMP_NAME.fullmatch(candidate.name))
    return _remove_orphans(candidates, max_age_seconds, warnings)


def cleanup_orphaned_temp_files_for(paths, max_age_seconds=ORPHAN_MAX_AGE_SECONDS, warnings=None):
    """Same sweep as `cleanup_orphaned_temp_files`, but scoped to the temp
    files a write to one of `paths` could have left behind -- only
    `<name>.<16 or 32 hex>.tmp` in each path's own parent folder, never a
    recursive scan. For a caller whose write surface is a handful of
    known files inside folders it doesn't own (a user's repository root,
    `.github/instructions/`, `~/.claude/skills/`), where sweeping the
    whole folder would reach content this tool never wrote."""
    candidates = []
    for path in dict.fromkeys(Path(path) for path in paths):
        own_temp = re.compile(re.escape(path.name) + _OWN_TEMP_SUFFIX)
        candidates.extend(
            candidate
            for candidate in path.parent.glob(glob.escape(path.name) + ".*.tmp")
            if own_temp.fullmatch(candidate.name)
        )
    return _remove_orphans(candidates, max_age_seconds, warnings)


def _remove_orphans(candidates, max_age_seconds, warnings):
    now = time.time()
    removed = []
    skipped = []
    for candidate in candidates:
        try:
            # Only a regular file is a temp this module wrote: a symlink
            # or junction carrying such a name is left alone, and never
            # aged by what it points to.
            info = candidate.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            age = now - info.st_mtime
        except FileNotFoundError:
            # Gone since the scan listed it -- typically a concurrent write
            # finishing its own os.replace. Nothing left to clean up.
            continue
        except OSError:
            skipped.append(candidate)
            continue
        if age > max_age_seconds:
            try:
                candidate.unlink(missing_ok=True)
                removed.append(candidate)
            except OSError:
                skipped.append(candidate)
    if warnings is not None and skipped:
        names = ", ".join(path.name for path in skipped)
        warnings.append(
            f"{len(skipped)} orphaned temp file(s) could not be checked/removed (permission denied or "
            f"similar), left for a later cleanup pass: {names}."
        )
    return removed
