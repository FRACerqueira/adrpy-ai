"""Builds the small set of human-readable warning strings for automatic,
non-fatal actions a command's own dependencies may take silently
otherwise: a retried write, orphaned temp-file cleanup, and invalid-byte
encoding repair. Every
mutating command's result carries these under "warnings" (an empty list
when nothing happened) so an agent calling the CLI can see them without
needing any external logging -- this is domain information that would
otherwise be discarded before it ever reached anywhere a log could
capture it, not a substitute for real operational logging (which stays
the executor's responsibility, per the project's own args-in/JSON-out
design)."""

import contextlib

from adrpy.core.output import explain
from adrpy.core.errors import CommandError, FailureCodes


@contextlib.contextmanager
def attach_warnings(warnings):
    """A real side effect already accumulated in `warnings` must survive ANY
    CommandError this same run goes on to raise afterward -- not just the
    raise sites living directly in a command's own cli/ module (already
    threaded explicitly at each site), but also one raised from a shared
    core/ helper the command calls (parse_refdate, validate_refdate_*,
    reject_embedded_delimiter, resolve_within). Wrap the
    whole region of a command's `run()` from where `warnings` starts
    accumulating onward.

    Merges rather than overwrites: an error that already carries its own
    warnings keeps
    them, with this command's own accumulated warnings prepended -- unless
    `error.warnings` is literally this same list (an explicit `warnings=
    warnings` already passed at the raise site), in which case there is
    nothing to merge."""
    try:
        yield
    except CommandError as error:
        if error.warnings is None:
            error.warnings = list(warnings)
        elif error.warnings is not warnings:
            error.warnings = list(warnings) + list(error.warnings)
        raise
    except OSError as error:
        # A real write failure (permission denied, full disk, a
        # PermissionError outlasting atomic_write's retry budget) would
        # otherwise propagate as a bare OSError -- this context manager
        # only catches CommandError on its own, so without this handler it
        # would bypass the whole mechanism entirely, reaching __main__'s
        # generic io-error with none of this run's
        # accumulated warnings attached. This is the safety net for every
        # write in the wrapped region; a site that needs to reveal a
        # PARTICULAR partial mutation (e.g. supersede's predecessor
        # already marked Superseded before its successor write failed)
        # still handles its own OSError explicitly, with tailored `data`,
        # before it would ever reach here.
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
    """`init` calls this only on the one branch where it has no informed
    source at all for the new config (no --seed, no --language, no
    per-machine install-level config) -- a first-time user on a fresh
    machine has no way to discover `installconfig` exists otherwise
    (confirmed: it's undocumented anywhere outside `adrpy help`
    itself)."""
    return (
        "No per-machine install-level config found -- seeded from the built-in default. "
        "Run `adrpy installconfig` once to set your own defaults for future repositories on "
        "this machine (see `adrpy help installconfig`)."
    )


def encoding_repaired_warning(path):
    """Only accurate once `path` itself has genuinely been rewritten --
    calling this before the write was even attempted (an ineligibility
    check could still fail first), or on `path`s this
    command never rewrites at all (version/revise's own source, which
    only ever donates its BODY to a newly created file -- see
    encoding_repaired_source_warning below). Callers append this only
    after the write to this exact path has actually succeeded."""
    return (
        f"{path}: invalid UTF-8 bytes were replaced with U+FFFD while reading; "
        "the original bytes are now lost, since the file has been rewritten."
    )


def excluded_candidate_warning(paths):
    """`core.security.is_within` deliberately never raises over a
    candidate whose real path escapes the repository boundary (e.g. a
    Windows junction planted inside the decisions folder) -- a scan
    should keep going, not fail over one. That's a decision about
    raising, not about reporting: without this warning, a scan call site
    would drop the exclusion with zero signal, leaving an agent no way to
    learn why an inventory or a next-number looks off from what's
    physically listable in the folder."""
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
    """ADR004V01: a hidden canonical status marker takes precedence over
    the status cell's visible label text when both are present. If they
    resolve to a valid but DIFFERENT status, that combination only
    happens when the visible word was hand-edited after the marker was
    written -- worth surfacing, since otherwise the marker's own
    silent-override would leave zero signal that this happened."""
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
