"""Human-readable warning strings for automatic, non-fatal actions a
command's dependencies would otherwise take silently: a retried write,
orphaned temp-file cleanup, invalid-byte encoding repair. Every mutating
command's result carries them under "warnings" (an empty list when
nothing happened), so a CLI caller sees them without external logging.
This is domain information, not a substitute for operational logging,
which stays the executor's responsibility (args in, JSON out)."""

import contextlib

from adrpy.core.output import explain
from adrpy.core.errors import CommandError, FailureCodes


@contextlib.contextmanager
def attach_warnings(warnings):
    """Wraps the region of a command's `run()` from where `warnings` starts
    accumulating onward, so the side effects recorded there survive ANY
    CommandError raised afterward -- including one from a shared core/
    helper (parse_refdate, validate_refdate_*, reject_embedded_delimiter,
    resolve_within), not only the raise sites in the command's own cli/
    module.

    Merges rather than overwrites: an error's own warnings are kept, with
    `warnings` prepended -- unless `error.warnings` is this same list
    (already passed at the raise site)."""
    try:
        yield
    except CommandError as error:
        if error.warnings is None:
            error.warnings = list(warnings)
        elif error.warnings is not warnings:
            error.warnings = list(warnings) + list(error.warnings)
        raise
    except OSError as error:
        # A bare OSError (permission denied, full disk, a PermissionError
        # outlasting atomic_write's retry budget) would otherwise reach
        # __main__'s generic io-error without this run's warnings. A site
        # that must report a PARTICULAR partial mutation (e.g. supersede's
        # predecessor already marked Superseded before its successor write
        # failed) handles its own OSError, with tailored `data`, first.
        raise CommandError(FailureCodes.IO_ERROR, explain(error), warnings=list(warnings)) from error


def orphan_cleanup_warning(removed, relative_to=None):
    """`relative_to`: name each file by its path under that folder instead
    of its bare name -- for a caller whose sweep spans several folders."""
    if not removed:
        return None

    def label(path):
        if relative_to is not None:
            try:
                return str(path.relative_to(relative_to))
            except ValueError:
                pass
        return path.name

    names = ", ".join(label(path) for path in removed)
    return f"Removed {len(removed)} orphaned temp file(s) left by an earlier interrupted write: {names}."


def retry_warning(attempts):
    if not attempts or attempts <= 1:
        return None
    return f"Write succeeded only after {attempts} attempts due to transient contention."


def no_install_level_config_warning():
    """`init` calls this only when it has no informed source for the new
    config (no --seed, no --language, no per-machine install-level
    config): it points a first-time user on a fresh machine at
    `installconfig`."""
    return (
        "No per-machine install-level config found -- seeded from the built-in default. "
        "Run `adrpy installconfig --<field> <value>` (e.g. `adrpy installconfig --language pt-br`) to set your "
        "own defaults for future repositories on this machine (see `adrpy help installconfig`)."
    )


def encoding_repaired_warning(path):
    """Only accurate once `path` itself has been rewritten: callers append
    it only after the write to this exact path succeeded -- never before
    the write (an ineligibility check could still fail first), and never
    for a path the command does not rewrite (version/revise's source,
    which only donates its BODY -- see encoding_repaired_source_warning)."""
    return (
        f"{path}: invalid UTF-8 bytes were replaced with U+FFFD while reading; "
        "the original bytes are now lost, since the file has been rewritten."
    )


def names_too_long_to_rewrite_warning(paths):
    """A decision whose name is past core/fs.MAX_NAME_BYTES reads fine but
    cannot be rewritten (its temp file's name would pass one name's limit):
    every command that changes it refuses with filename-too-long. None when
    no such name exists."""
    from adrpy.core.fs import MAX_NAME_BYTES, name_bytes

    names = sorted(path.name for path in paths if name_bytes(path.name) > MAX_NAME_BYTES)
    if not names:
        return None
    return (
        f"{len(names)} decision name(s) are longer than the {MAX_NAME_BYTES} bytes this tool can rewrite: "
        "a command that changes them refuses with filename-too-long. Rename each by hand to a shorter title "
        f"part, keeping its number, version, revision and any --NNN suffix: {', '.join(names)}."
    )


def linked_decisions_warning(paths):
    """The `.md` files in the decisions folder that are symbolic links:
    every command that would rewrite one refuses with target-is-a-link.
    None when there is none."""
    if not paths:
        return None
    names = sorted(str(path) for path in paths)
    return (
        f"{len(names)} .md file(s) in the decisions folder are symbolic links: a command that would rewrite "
        "one refuses with target-is-a-link. Replace each link with the file it points to, or remove it: "
        f"{', '.join(names)}."
    )


def excluded_candidate_warning(paths):
    """`core.fs.scan_tree` never fails over a candidate whose real path
    escapes the folder (e.g. a Windows junction planted inside the
    decisions folder): it excludes it and keeps going. This warning
    reports the exclusion; without it an agent could not tell why an
    inventory or a next number differs from what the folder physically
    lists."""
    if not paths:
        return None
    # Sorted: a scan finds them in the folder's listing order, which
    # differs between filesystems.
    names = ", ".join(sorted(str(path) for path in paths))
    return (
        f"{len(paths)} candidate file(s) or folder(s) were excluded from this scan because their real path "
        f"escapes the repository boundary (e.g. a symlink/junction): {names}."
    )


def marker_label_mismatch_warning(header):
    """ADR0004V01: a hidden canonical status marker takes precedence over
    the status cell's visible label text. When both resolve to valid but
    DIFFERENT statuses, the visible word was hand-edited after the marker
    was written; without this warning the marker's override would leave
    no signal."""
    if not header.marker_label_mismatches:
        return None
    names = ", ".join(header.marker_label_mismatches)
    return (
        f"{names}: the status cell's hidden marker and its visible label text disagree -- the marker "
        "(authoritative) was used; the visible word may have been hand-edited after the marker was written."
    )


def encoding_repaired_source_warning(path):
    """For a read-only source whose BODY is carried into a newly created
    file (version/revise) -- `path` itself is never rewritten by these
    commands, so encoding_repaired_warning's "the file has been
    rewritten" claim is never true here, success or failure."""
    return (
        f"{path}: invalid UTF-8 bytes were replaced with U+FFFD while reading its body; "
        "the source file itself is unchanged, but a new file created from this content "
        "would carry the replacement forward permanently."
    )
