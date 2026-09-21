"""`config` command: updates fields of an existing repository's own
`adr-config.adrplus` directly.

Deliberate, confirmed divergence from the reference tool: its own `config
--repository/--application/--template/--migrate` never edit an existing
repo's own file -- only the interactive wizard (or `init --file`, which
overwrites everything) does. adrpy-ai has no wizard, so this command
exists instead: one flag per config field, merge/update semantics -- an
omitted flag preserves the repo's current value, never resets it.

`activeplugins` is deliberately not exposed here -- the plugin system is
out of scope for now (confirmed decision). `disableplugins` IS exposed
(it's a meaningful kill-switch field even with no plugins implemented,
harmless either way) but needs an explicit true/false value, not a
presence-only switch, since either direction is a real edit.
"""

import json
from dataclasses import asdict

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core import config as config_schema
from adrpy.core.config import _INT_FIELDS, _STRING_FIELDS, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    reject_folderadr_change_if_decisions_exist,
    reject_status_or_separator_change_if_decisions_exist,
    resolve_target_and_config,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, retry_warning

_BOOLEAN_FIELD_FLAGS = ("disableplugins",)
_EDITABLE_FIELDS = _STRING_FIELDS + _INT_FIELDS + _BOOLEAN_FIELD_FLAGS


def _field_type(field):
    if field in _INT_FIELDS:
        return "integer"
    if field in _BOOLEAN_FIELD_FLAGS:
        return "boolean"
    return "string"


_INT_FIELD_BOUNDS = {
    "lenseq": (config_schema.LENSEQ_MIN, config_schema.LENSEQ_MAX),
    "lenversion": (config_schema.LENVERSION_MIN, config_schema.LENVERSION_MAX),
    "lenrevision": (config_schema.LENREVISION_MIN, config_schema.LENREVISION_MAX),
}


def _field_description(field):
    """Cites the same constants core/config.py's own
    validator enforces (never a hand-copied number), so a field's real
    domain is discoverable via `help config` instead of only by
    deliberately triggering the matching config-*-invalid/-too-long
    error -- and the two can never silently drift apart."""
    if field == "folderadr":
        return (
            f"Relative path to the decisions folder, max {config_schema.FOLDERADR_MAX_LENGTH} characters; "
            "cannot be empty, absolute, or escape the repository."
        )
    # "may be empty" describes the STORED value's own schema rule (no
    # cannot-be-empty validation for these 3) -- it does NOT mean this
    # flag can set it to empty. Every
    # optional flag goes through parse_flags, which rejects an empty
    # string outright before ever reaching the field; only `init --seed`
    # (which bypasses parse_flags, reading an arbitrary JSON file) can
    # actually persist an empty value here.
    if field == "migrationpattern":
        return (
            "Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' "
            "(N##:##T##[V##:##][R##:##][P##:##]); the stored value may be empty, but this flag can't set it "
            "to an empty string here (parse_flags rejects any empty optional value outright) -- use "
            "`init --seed` for that."
        )
    if field == "template":
        return (
            "Default template content for a new decision's body; the stored value may be empty, but this "
            "flag can't set it to an empty string here (parse_flags rejects any empty optional value "
            "outright) -- use `init --seed` for that."
        )
    if field == "prefix":
        return (
            f"ASCII letters only, max {config_schema.PREFIX_MAX_LENGTH} characters; the stored value may be "
            "empty, but this flag can't set it to an empty string here (parse_flags rejects any empty "
            "optional value outright) -- use `init --seed` for that."
        )
    if field == "separator":
        return f"One of {config_schema.VALID_SEPARATORS}."
    if field == "casetransform":
        return f"One of {config_schema.VALID_CASE_TRANSFORMS}."
    # These 16 fields (4 status labels + 11 header labels +
    # headerdisclaimer) all go through reject_embedded_delimiter
    # (core/config.py's own validator) on top of their length bound -- an
    # agent following only the stated domain (any string <= max length,
    # non-empty) could otherwise still hit
    # config-field-contains-forbidden-character with no prior warning.
    if field in config_schema._STATUS_LABEL_FIELDS:
        return (
            f"Status label shown in the header table, max {config_schema.STATUS_LABEL_MAX_LENGTH} "
            "characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot "
            "contain '(', ')', '<!--', or '-->' -- these four fields alone land inside the status cell's own "
            "parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker), so one of these "
            "characters could otherwise forge a date/marker the tool never wrote."
        )
    if field == "headerdisclaimer":
        return (
            f"Header disclaimer text, max {config_schema.HEADER_DISCLAIMER_MAX_LENGTH} characters; "
            "cannot be empty, contain '|', or contain a line-break-like character."
        )
    if field in config_schema._HEADER_LABEL_FIELDS_MAX_40:
        return (
            f"Header row label, max {config_schema.HEADER_LABEL_MAX_LENGTH} characters; cannot be empty, "
            "contain '|', or contain a line-break-like character."
        )
    if field in _INT_FIELD_BOUNDS:
        low, high = _INT_FIELD_BOUNDS[field]
        return f"Integer between {low} and {high} (inclusive)."
    if field == "disableplugins":
        return "'true' or 'false'."
    # Unreachable today -- every field in _EDITABLE_FIELDS hits a branch
    # above. A silent, generic fallback here (a tautological "New value
    # for '<field>'." an agent can't learn anything from) would return
    # the moment a new field is ever added to _EDITABLE_FIELDS without a
    # matching branch -- fail loudly instead.
    raise AssertionError(f"No description defined for editable field '{field}'.")


def describe():
    return {
        "name": "config",
        "summary": "Reads or updates an existing repository's own adr-config.adrplus.",
        "description": (
            "Reads or updates fields of an existing repository's adr-config.adrplus. "
            "With no field flags, reads the current config back (read-only, no write). "
            "`activeplugins` is never included in that read result or accepted as a field to update -- "
            "the plugin system is out of scope for now (see the `init` command's own note) -- "
            "so this is a subset of the raw file, not its full contents; do not round-trip it as "
            "`init --seed` input without adding `activeplugins` back. "
            "Omitted fields keep their current value; only the fields passed are updated. "
            "The result's own JSON shape differs by mode: a pure read's result has a `config` key (the "
            "current field values); a write's result never has that key at all, only `updated_fields` -- a "
            "generic wrapper that reads `data.config` unconditionally after any `config` call will KeyError "
            "on a write. "
            "--folderadr can only be changed while the OLD folder has no recognized decisions yet -- "
            "otherwise fails with folderadr-change-blocked-by-existing-decisions (data.existing_decisions "
            "names the count) rather than silently orphaning them at their old, still-real path; if that "
            "check itself can't be completed (a subdirectory couldn't be scanned), fails closed instead with "
            "folderadr-change-scan-incomplete rather than assuming nothing was there. The NEW folder is "
            "checked too: if it already exists and holds a file that would newly parse as a decision under "
            "the resulting config, fails with folderadr-change-would-adopt-unrelated-files "
            "(data.adopted_files lists the file paths) instead of silently absorbing it and corrupting "
            "next-number allocation -- the same scan-incomplete code above covers an unreadable subdirectory "
            "under the new folder too. Skipped entirely when the new folder does not exist yet. "
            "--statusnew/--statusacc/--statusrej/--statussup/--separator/--migrationpattern can likewise only "
            "be changed while doing so would not break recognition of an existing decision (ADR004V01/V02) -- "
            "otherwise fails with status-or-separator-change-blocked-by-existing-decisions "
            "(data.changed_fields names only the guarded field(s) actually blocking this call -- a field this "
            "call also touched, but whose own scope has no existing decisions at risk, is NOT listed there "
            "even though the call's atomic write still fails to apply it either; data.existing_decisions is "
            "the decision count actually at risk from those blocking field(s), not necessarily the "
            "repository's total). Status labels and --separator block if ANY recognized decision exists "
            "(current-scheme or legacy-scheme -- --separator's own recognition dependency is CURRENT-scheme-"
            "only, but a value that already appears inside a legacy filename can make that file newly match "
            "the current-scheme parser too, silently reclassifying it, so --separator cannot be scoped to "
            "current-scheme decisions the way --migrationpattern safely can); --migrationpattern blocks only "
            "if a LEGACY-scheme decision exists (parse_filename, the current-scheme parser, never reads "
            "migrationpattern, so no equivalent reclassification risk exists in that direction). This is a "
            "PERMANENT block once the decisions it actually protects exist, with no migration path -- for "
            "--statusnew/--statusacc/--statusrej/--statussup and --separator that means ANY recognized "
            "decision, any scheme (the ADR004V01 marker future-proofs RECOGNITION of files that already carry "
            "it against a later label change, but does not exempt THIS GUARD from refusing the config change "
            "itself -- the two are independent, and a marker-protected repository is blocked exactly the same "
            "as one with none); for --migrationpattern it means a LEGACY-scheme decision specifically. Same "
            "scan-incomplete fail-closed shape as folderadr's "
            "own guard: status-or-separator-change-scan-incomplete, whose own data.changed_fields DOES list "
            "every guarded field the call touched (not just the blocking ones) -- an unreadable subdirectory's "
            "own contents can't be ruled out for any guarded field, so this one fails closed unconditionally. "
            "--separator may also fail with separator-change-would-adopt-unrelated-files (data.adopted_files "
            "lists the file paths) if changing it would make a file NOT currently recognized as a decision "
            "(by either naming scheme) newly parse as one -- unlike --migrationpattern, which is deliberately "
            "allowed to newly recognize pre-existing legacy files (that is its own documented purpose), "
            "--separator has no such intentional-adoption use case, so any file it would newly sweep in is "
            "treated as an unintended side effect and blocked. This check only ever runs once the "
            "blocked-by-existing-decisions check above has already passed, so it only ever fires when zero "
            "existing decisions are at risk from this call -- not an edge case alongside a more common one "
            "where both could coexist, since those two outcomes are mutually exclusive by construction. "
            "A write call may also fail with repository-locked if the repository lock could not be "
            "acquired in time, or lock-lost if it was acquired but reclaimed before the write could "
            "commit -- in both cases no write was made; a pure read (no field flags) never takes the lock. "
            "May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved "
            "folderadr while this call was acquiring the lock -- no write was made either way; retry."
        ),
        "arguments": [
            {"name": "path", "type": "string", "required": True, "description": "Repository root directory."},
            *[
                {
                    "name": field,
                    "type": _field_type(field),
                    "required": False,
                    "description": _field_description(field),
                }
                for field in _EDITABLE_FIELDS
            ],
        ],
    }


def run(args):
    flags = parse_flags(args, required=("path",), optional=_EDITABLE_FIELDS)
    target, config_path, config = resolve_target_and_config(flags["path"])

    # Which fields (if any) this call would touch is knowable from the
    # flags alone, before reading the file at all -- a pure read (no
    # field flags) never needs the repository lock below, matching
    # explore's own precedent.
    if not any(field in flags for field in _EDITABLE_FIELDS):
        # There was no way to read the current config through the JSON
        # contract at all, and calling this with no field flags -- the
        # natural way an agent would try to "just look" -- still rewrote
        # (and reformatted) the file as a side effect of what looks like a
        # read-only call. `activeplugins` stays excluded, same as a write.
        current_fields = {field: getattr(config, field) for field in _EDITABLE_FIELDS}
        return {"file": str(config_path), "updated_fields": [], "config": current_fields, "warnings": []}

    # A read-merge-write with no lock would let two concurrent calls
    # editing DIFFERENT fields silently lose one of the two edits,
    # contradicting this command's own documented contract above ("an
    # omitted flag preserves the repo's current value, never resets it").
    # Uses the same repository lock the other 8 write commands already
    # use, scoped to folderadr -- resolved here from the pre-edit config
    # just to know where the lock lives; the actual merge below re-reads
    # fresh, inside the lock (ADR001's own freshness principle), so even
    # a concurrent edit to folderadr itself is safe: whichever call
    # writes second still merges its own field onto the other's
    # already-committed change.
    bootstrap_config = config
    folder = resolve_within(target, bootstrap_config.folderadr)
    # Unlike the other 8 commands (which only ever run after `init`
    # already created this directory), nothing requires it to exist
    # before `config` runs -- ensure it does, matching init's own
    # precedent, or acquiring the lock inside it would raise a raw
    # FileNotFoundError (core.lock._try_create only handles
    # FileExistsError, not a missing parent directory).
    folder.mkdir(parents=True, exist_ok=True)

    warnings = []
    with attach_warnings(warnings):
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # `folder` above (this lock's own location) was resolved from
            # `bootstrap_config`, read BEFORE the lock. Re-reads fresh and
            # aborts if folderadr already drifted in that window, instead
            # of trusting the pre-lock read.
            current = verify_folderadr_unchanged_since_lock(
                config_path, bootstrap_config.folderadr, warnings=warnings
            )
            merged = asdict(current)
            updated_fields = []

            for field in _STRING_FIELDS:
                if field in flags:
                    merged[field] = flags[field]
                    updated_fields.append(field)

            for field in _INT_FIELDS:
                if field in flags:
                    try:
                        merged[field] = int(flags[field])
                    except ValueError as error:
                        raise CommandError(
                            "field-not-an-integer", f"--{field} must be an integer, got: {flags[field]}"
                        ) from error
                    updated_fields.append(field)

            if "disableplugins" in flags:
                text = flags["disableplugins"].strip().lower()
                if text not in ("true", "false"):
                    raise CommandError(
                        "field-not-a-boolean", "--disableplugins must be 'true' or 'false'."
                    )
                merged["disableplugins"] = text == "true"
                updated_fields.append("disableplugins")

            merged_text = json.dumps(merged, indent=2, ensure_ascii=False)
            new_config = parse_repo_config(merged_text)  # re-validates the merged result; raises on failure

            # _is_relative_path only rejects an anchored escape ("C:\..",
            # "\\server\.."); "../../evil" is still relative and passes that check,
            # but resolves outside the repository -- validate before writing, the
            # same order `init` already uses, so a hostile --folderadr can never
            # get persisted and brick the repository (every subsequent command
            # would refuse with path-outside-repository until hand-fixed).
            resolve_within(target, new_config.folderadr)

            # A folderadr change is only valid when the OLD folder has no
            # recognized decisions yet -- otherwise every existing
            # decision becomes invisible at its old, still-real path, and
            # a command running before vs. after this write would lock
            # two different directories that never exclude each other.
            # Checked against `current` (fresh, inside the lock) and
            # `folder` (this same lock's own location) -- both are the
            # pre-edit state.
            reject_folderadr_change_if_decisions_exist(
                folder,
                current.folderadr,
                new_config.folderadr,
                current,
                target=target,
                new_config=new_config,
                warnings=warnings,
            )

            # ADR004V01: a statusnew/statusacc/statusrej/statussup or
            # separator change is only valid when the OLD folder has no
            # recognized decisions yet -- otherwise some or all of them
            # stop being recognized (a label change breaks a marker-less
            # status cell's text match; a separator change breaks
            # filename recognition entirely). Same `folder`/`current`
            # pre-edit state as the folderadr guard above.
            reject_status_or_separator_change_if_decisions_exist(folder, current, new_config, warnings=warnings)

            # Creating the new folder here, BEFORE the config commits,
            # means a failure creating it aborts cleanly with nothing yet
            # written -- committing folderadr to disk first instead would
            # leave the repository pointing at a directory that didn't
            # exist, with no `data` naming that already-committed change,
            # and every subsequent command failing with a generic io-error
            # until someone noticed and retried. mkdir is otherwise
            # harmless if the write below
            # still somehow fails afterward -- an unused empty folder, not
            # a real cost.
            new_folder = resolve_within(target, new_config.folderadr)
            new_folder.mkdir(parents=True, exist_ok=True)

            # ADR001, part 3: guarantees this write never commits blindly
            # if the lease was reclaimed.
            lock.verify_still_held()
            attempts = atomic_write_text(config_path, merged_text)
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    return {"file": str(config_path), "updated_fields": updated_fields, "warnings": warnings}
