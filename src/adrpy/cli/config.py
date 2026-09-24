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
from adrpy.core.config import INT_FIELD_BOUNDS, _INT_FIELDS, _STRING_FIELDS, parse_repo_config
from adrpy.core.consistency import validate_repository
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.fs import scan_tree
from adrpy.core.lifecycle import (
    guarded_fields_changed,
    resolve_target_and_config,
    validate_config_change,
)
from adrpy.core.text import parse_ascii_int
from adrpy.core.security import reject_aliased_repo_folders, resolve_within
from adrpy.core.warnings import attach_warnings, retry_warning

_BOOLEAN_FIELD_FLAGS = ("disableplugins",)
_EDITABLE_FIELDS = _STRING_FIELDS + _INT_FIELDS + _BOOLEAN_FIELD_FLAGS


def _field_type(field):
    if field in _INT_FIELDS:
        return "integer"
    if field in _BOOLEAN_FIELD_FLAGS:
        return "boolean"
    return "string"


def _field_description(field):
    """Cites the same constants core/config.py's own
    validator enforces (never a hand-copied number), so a field's real
    domain is discoverable via `help config` instead of only by
    deliberately triggering the matching config-*-invalid/-too-long
    error -- and the two can never silently drift apart."""
    if field == "folderadr":
        return (
            f"Relative path to the decisions folder, max {config_schema.FOLDERADR_MAX_LENGTH} characters; "
            "cannot be empty, absolute, escape the repository, or resolve to the repository root itself."
        )
    if field == "folderlog":
        return (
            f"Relative path to the decision-log directory (ADR007V01), max "
            f"{config_schema.FOLDERLOG_MAX_LENGTH} characters; cannot be empty, absolute, escape the "
            "repository, or be the same as (or nested inside/around) folderadr "
            "(config-folderadr-folderlog-overlap). Defaults to folderadr's own parent sibling "
            "'decision-log' when omitted from a hand-edited config written before this field existed."
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
            f"Default template content for a new decision's body, max {config_schema.TEMPLATE_MAX_LENGTH} "
            "characters; a too-long value fails with config-template-too-long. The stored value may be "
            "empty, but this flag can't set it to an empty string here (parse_flags rejects any empty "
            "optional value outright) -- use `init --seed` for that."
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
            "contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status "
            "cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and "
            "the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), "
            "so one of these characters could otherwise forge a date/marker the tool never wrote, or "
            "corrupt which successor a Superseded row points to."
        )
    if field == "headerdisclaimer":
        return (
            f"Header disclaimer text, max {config_schema.HEADER_DISCLAIMER_MAX_LENGTH} characters; "
            "cannot be empty, contain '|', or contain a line-break-like character."
        )
    if field in ("headertablefields", "headertablevalues"):
        return (
            f"Header row label, max {config_schema.HEADER_LABEL_MAX_LENGTH} characters; cannot be empty, "
            "contain '|', or contain a line-break-like character. Also cannot contain '<!--' or '-->' -- "
            "these two build the header's table row, where an HTML comment is the migrated-header marker."
        )
    if field in config_schema._HEADER_LABEL_FIELDS_MAX_40:
        return (
            f"Header row label, max {config_schema.HEADER_LABEL_MAX_LENGTH} characters; cannot be empty, "
            "contain '|', or contain a line-break-like character."
        )
    if field in INT_FIELD_BOUNDS:
        low, high = INT_FIELD_BOUNDS[field]
        return (
            f"Integer between {low} and {high} (inclusive); a non-integer value fails with "
            "field-not-an-integer."
        )
    if field == "disableplugins":
        return "'true' or 'false'; anything else fails with field-not-a-boolean."
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
            "May fail with target-directory-not-found if --path does not point to an existing directory, "
            "or config-not-found if that directory has no adr-config.adrplus -- no write is attempted "
            "either way. "
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
            "Before changing a guarded field (--folderadr, --folderlog, --statusnew/--statusacc/--statusrej/"
            "--statussup, --separator, --migrationpattern), the repository is validated with the current "
            "config: if it breaks a consistency rule (the ones `adrpy check` reports, a subdirectory of the "
            "decisions folder that could not be scanned included), fails with repository-inconsistent, "
            "every broken rule listed in data.errors with a repair hint, and nothing is written. A read, or "
            "a change of any other field, does not validate. "
            "--folderadr can only be changed while the OLD folder has no recognized decisions yet -- "
            "otherwise fails with folderadr-change-blocked-by-existing-decisions (data.existing_decisions "
            "names the count) rather than silently orphaning them at their old, still-real path. The NEW folder is "
            "checked too: if it already exists and holds a file that would newly parse as a decision under "
            "the resulting config, fails with folderadr-change-would-adopt-unrelated-files "
            "(data.adopted_files lists the file paths) instead of silently absorbing it and corrupting "
            "next-number allocation; if a subdirectory under the new folder can't be scanned, fails closed with "
            "folderadr-change-scan-incomplete rather than assuming nothing was there. Skipped entirely when "
            "the new folder does not exist yet. "
            "--folderlog (ADR007V01, deliberately not byte-compatible with the reference tool's own schema) "
            "is validated and change-guarded the same way -- cannot overlap with (equal, or be nested inside "
            "or around) folderadr, fails with config-folderadr-folderlog-overlap otherwise; can only be "
            "changed while the OLD directory has no decision-log entries yet, otherwise fails with "
            "folderlog-change-blocked-by-existing-entries (data.existing_entries names the count); the NEW "
            "directory is checked too, failing with folderlog-change-would-adopt-unrelated-files "
            "(data.adopted_files: bare filenames, not paths) if it already holds a file that would newly parse as an entry -- unlike "
            "folderadr's own scan, decision-log's own scan additionally fails LOUDLY "
            "(log-directory-contains-unrecognized-file) on any .md file there that does NOT parse as a valid "
            "entry, rather than silently ignoring it, since that scan can never tell 'unrelated' apart from "
            "'malformed' the way folderadr's naming-scheme recognition can. Both directions fail closed with "
            "log-scan-incomplete if a subdirectory can't be scanned. Omitted from a hand-edited config "
            "written before this field existed, folderlog defaults to folderadr's own parent sibling "
            "'decision-log' -- this command's own read/write both honor that default transparently. "
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
            "as one with none); for --migrationpattern it means a LEGACY-scheme decision specifically. "
            "--separator may also fail with separator-change-would-adopt-unrelated-files (data.adopted_files "
            "lists the file paths) if changing it would make a file NOT currently recognized as a decision "
            "(by either naming scheme) newly parse as one -- unlike --migrationpattern, which is deliberately "
            "allowed to newly recognize pre-existing legacy files (that is its own documented purpose), "
            "--separator has no such intentional-adoption use case, so any file it would newly sweep in is "
            "treated as an unintended side effect and blocked. This check only ever runs once the "
            "blocked-by-existing-decisions check above has already passed, so it only ever fires when zero "
            "existing decisions are at risk from this call -- not an edge case alongside a more common one "
            "where both could coexist, since those two outcomes are mutually exclusive by construction."
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
        "failure_codes": build_failure_codes(
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_NOT_FOUND: "--path's own directory has no adr-config.adrplus.",
                FailureCodes.FIELD_NOT_AN_INTEGER: "An integer field's own value is not a valid integer.",
                FailureCodes.FIELD_NOT_A_BOOLEAN: "--disableplugins is not 'true' or 'false'.",
                FailureCodes.REPOSITORY_INCONSISTENT: "A guarded field is being changed and the decisions folder breaks at least one consistency rule (the same ones `adrpy check` reports); data.errors lists every one, with its file and a repair hint. Nothing is written until the repository is repaired.",
                FailureCodes.FOLDERADR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS: "--folderadr can only be changed while the OLD folder has no recognized decisions yet.",
                FailureCodes.FOLDERADR_CHANGE_SCAN_INCOMPLETE: "A subdirectory under the NEW folderadr could not be scanned while checking a --folderadr change.",
                FailureCodes.FOLDERADR_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "The NEW folderadr already holds a file that would newly parse as a decision.",
                FailureCodes.FOLDERADR_FOLDERLOG_ALIAS_SAME_DIRECTORY: "folderadr and folderlog resolve to the same real directory (or one nested inside the other), typically via a symlink or junction.",
                FailureCodes.FOLDERLOG_CHANGE_BLOCKED_BY_EXISTING_ENTRIES: "--folderlog can only be changed while the OLD directory has no decision-log entries yet.",
                FailureCodes.FOLDERLOG_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "The NEW folderlog already holds a file that would newly parse as a decision-log entry.",
                FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE: "The OLD or NEW folderlog contains a .md file that does not parse as a valid decision-log entry.",
                FailureCodes.LOG_SCAN_INCOMPLETE: "A subdirectory under the OLD or NEW folderlog could not be scanned while checking a --folderlog change.",
                FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS: "A status-label/--separator/--migrationpattern change would break recognition of an existing decision.",
                FailureCodes.SEPARATOR_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "--separator would make a file NOT currently recognized as a decision newly parse as one.",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
                FailureCodes.IO_ERROR: "The write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
            },
            config_schema.SHARED_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(args, required=("path",), optional=_EDITABLE_FIELDS)
    target, config_path, config = resolve_target_and_config(flags["path"])

    # Which fields (if any) this call would touch is knowable from the
    # flags alone -- a pure read (no field flags) writes nothing,
    # matching explore's own precedent.
    if not any(field in flags for field in _EDITABLE_FIELDS):
        # There was no way to read the current config through the JSON
        # contract at all, and calling this with no field flags -- the
        # natural way an agent would try to "just look" -- still rewrote
        # (and reformatted) the file as a side effect of what looks like a
        # read-only call. `activeplugins` stays excluded, same as a write.
        current_fields = {field: getattr(config, field) for field in _EDITABLE_FIELDS}
        return {"file": str(config_path), "updated_fields": [], "config": current_fields, "warnings": []}

    current = config
    folder = resolve_within(target, current.folderadr)
    # Nothing requires this directory to exist before `config` runs --
    # ensure it does, matching init's own precedent: the folderadr/
    # status/separator guards below scan it, and scan_tree treats a
    # missing folder as unreadable.
    folder.mkdir(parents=True, exist_ok=True)

    warnings = []
    with attach_warnings(warnings):
        merged = asdict(current)
        updated_fields = []

        for field in _STRING_FIELDS:
            if field in flags:
                merged[field] = flags[field]
                updated_fields.append(field)

        for field in _INT_FIELDS:
            if field in flags:
                try:
                    merged[field] = parse_ascii_int(flags[field])
                except ValueError as error:
                    raise CommandError(
                        FailureCodes.FIELD_NOT_AN_INTEGER, f"--{field} must be an integer, got: {flags[field]}"
                    ) from error
                updated_fields.append(field)

        if "disableplugins" in flags:
            text = flags["disableplugins"].strip().lower()
            if text not in ("true", "false"):
                raise CommandError(
                    FailureCodes.FIELD_NOT_A_BOOLEAN, "--disableplugins must be 'true' or 'false'."
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

        # The new folderlog can't escape the repository either, and the
        # schema-time guard in core/config.py's own parse_repo_config can
        # never see a junction/symlink planted inside the repo tree --
        # re-checked here, against the real, resolved directories, before
        # anything is created.
        resolve_within(target, new_config.folderlog)
        reject_aliased_repo_folders(target, new_config)

        # A guarded field (folderadr, folderlog, a status label,
        # separator, migrationpattern) changes only on a consistent
        # repository, and only when no existing decision or log entry
        # would be orphaned, unrecognized or silently adopted -- one scan
        # of the pre-edit folder feeds both checks.
        if guarded_fields_changed(current, new_config):
            scan = scan_tree(folder)
            validate_repository(folder, current, scan=scan)
            validate_config_change(current, new_config, folder, target=target, scan=scan, warnings=warnings)

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

        attempts = atomic_write_text(config_path, merged_text)
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    return {"file": str(config_path), "updated_fields": updated_fields, "warnings": warnings}
