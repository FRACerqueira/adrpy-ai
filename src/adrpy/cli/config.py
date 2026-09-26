"""`config` command: updates fields of an existing repository's own
`adr-config.adrplus` directly.

adrpy-ai has no interactive wizard, so this command is how an existing
repository's settings change: one flag per config field, merge/update
semantics -- an omitted flag preserves the repo's current value, never
resets it.

`activeplugins` is deliberately not exposed here -- the plugin system is
out of scope. `disableplugins` IS exposed
(it's a meaningful kill-switch field even with no plugins implemented,
harmless either way) but needs an explicit true/false value, not a
presence-only switch, since either direction is a real edit.
"""

from dataclasses import asdict

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core import config as config_schema
from adrpy.core.config import (
    INT_FIELD_BOUNDS,
    _INT_FIELDS,
    _STRING_FIELDS,
    parse_repo_config,
    reject_overlapping_migration_pattern,
    serialize_repo_config,
)
from adrpy.core.consistency import validate_repository
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.fs import cleanup_orphaned_temp_files_for, make_dirs, remove_created_dirs, scan_tree
from adrpy.core.lifecycle import (
    PATTERN_ADVICE_BEFORE_MIGRATE,
    guarded_fields_changed,
    legacy_pattern_preview,
    legacy_pattern_warnings,
    resolve_target_and_config,
    validate_config_change,
)
from adrpy.core.text import parse_ascii_int
from adrpy.core.security import reject_aliased_repo_folders, resolve_within
from adrpy.core.warnings import attach_warnings, orphan_cleanup_warning, retry_warning

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
    # cannot-be-empty validation for template/prefix) -- it does NOT mean
    # the flag can set it to empty: parse_flags rejects an empty optional
    # value outright, except for migrationpattern (allow_empty in run),
    # so only `init --seed` can persist an empty template or prefix.
    if field == "migrationpattern":
        return (
            "Positional pattern for the legacy naming scheme (N##:##T##[V##:##][R##:##][P##:##]): N is the "
            "number's start:length in the name without '.md', T where the title starts (after the separator), "
            "V/R/P the version's, revision's and prefix's start:length, positions from 00 -- e.g. 'N00:04T05' "
            "for `0001-title.md`, 'N00:04T04' for `0001Title.md`. Setting it writes the config: preview a "
            "pattern first with `adrpy explore --path . --migrationpattern <pattern>`, which writes nothing. "
            "The result lists what it recognizes (migrationpattern_preview) and warns about a likely "
            "misreading. A pattern that reads part of a name twice -- its T starts inside its N/V/R/P range, "
            "or two of those ranges overlap, as 'N00:04T02' for `0001-title.md` (title '01-title') -- is "
            "refused with config-migrationpattern-invalid, the detail naming the overlap; a config that "
            "already holds one still loads, and this flag can clear or correct it while no decision was migrated with "
            "it (after that the guard keeps it, and migrate finishes with it and warns). While the repository is not adopted yet (no file has a valid header migrate did not "
            "write, so migrate can still run), `adrpy check` (and every command that "
            "validates the repository) then fails with no-header on each file it matches until `adrpy migrate` runs; once a decision has a "
            "valid header migrate did not write, a file it matches without one is not a decision. To back out, an empty value "
            "(--migrationpattern \"\") clears it. Like "
            "any change to it, clearing is refused (status-or-separator-change-blocked-by-existing-decisions) "
            "while a LEGACY-scheme decision that already has a header (migrated) would lose recognition; "
            "hand-written files it only matches by name do not block it."
        )
    if field == "template":
        return (
            f"Default template content for a new decision's body, max {config_schema.TEMPLATE_MAX_LENGTH} "
            "characters; a too-long value fails with config-template-too-long. The stored value may be "
            "empty, but this flag can't set it to an empty string here (an empty value for this flag is "
            "refused as a usage error) -- use `init --seed` for that."
        )
    if field == "prefix":
        return (
            f"ASCII letters only, max {config_schema.PREFIX_MAX_LENGTH} characters; every decision name starts "
            "with it (compared case-insensitively), so it is guarded like --separator. The stored value may be "
            "empty, but this flag can't set it to an empty string here (an empty value for this flag is "
            "refused as a usage error) -- use `init --seed` for that."
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
            "With no field flags, reads the repository's adr-config.adrplus back (the result has a `config` "
            "key); otherwise updates only the fields passed (the result has `updated_fields` and no `config` "
            "key). Changing a guarded field -- folderadr, folderlog, a status label, separator, prefix or "
            "migrationpattern -- validates the repository first and is refused while it would orphan, "
            "reclassify or adopt existing files (ADR004V02, ADR007V01). Setting migrationpattern writes the config "
            "and also returns `migrationpattern_preview` (file, number, version, title of each file it "
            "recognizes); `adrpy explore --path . --migrationpattern <pattern>` returns the same preview "
            "without writing anything, so preview there first. While the repository is not adopted yet, check "
            "then fails with no-header on each file the pattern matches until `adrpy migrate` runs; once a "
            "decision migrate did not write exists, such a file is only warned about. To back out, "
            "--migrationpattern \"\". "
            "`activeplugins` is never read or written."
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
                FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS: "A status-label/--separator/--prefix change would break recognition of an existing decision, or a --migrationpattern change that of a legacy-scheme decision that already has a header (migrated).",
                FailureCodes.SEPARATOR_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "--separator would make a file NOT currently recognized as a decision newly parse as one.",
                FailureCodes.PREFIX_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "--prefix would make a file NOT currently recognized as a decision newly parse as one (data.adopted_files).",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
                FailureCodes.IO_ERROR: "The write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
            },
            config_schema.SHARED_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(args, required=("path",), optional=_EDITABLE_FIELDS, allow_empty=("migrationpattern",))
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

    warnings = []
    with attach_warnings(warnings):
        warning = orphan_cleanup_warning(cleanup_orphaned_temp_files_for([config_path], warnings=warnings))
        if warning:
            warnings.append(warning)
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

        merged_text = serialize_repo_config(merged)
        new_config = parse_repo_config(merged_text)  # re-validates the merged result; raises on failure
        # Only the value being set: one already stored is left loadable.
        if "migrationpattern" in flags:
            reject_overlapping_migration_pattern(new_config.migrationpattern)

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

        # Every folder this call creates (the one it scans, the new
        # folderadr), and each missing parent of it, is removed again,
        # bottom-up, when the guard refuses the change or anything else
        # fails before the write -- never a folder that existed or has
        # received content.
        created = []
        try:
            # A guarded field (folderadr, folderlog, a status label,
            # separator, migrationpattern) changes only on a consistent
            # repository (files with no header aside), and only when no existing decision or log entry
            # would be orphaned, unrecognized or silently adopted -- one scan
            # of the pre-edit folder feeds both checks.
            if guarded_fields_changed(current, new_config):
                # Nothing requires this directory to exist before `config`
                # runs -- ensure it does, now that the new values are valid,
                # matching init's own precedent: the folderadr/status/
                # separator/prefix guards below scan it, and scan_tree treats
                # a missing folder as unreadable.
                created.append((folder, make_dirs(folder)))
                scan = scan_tree(folder)
                # no-header is tolerated: before its one migrate a repository
                # is made of such files, and migrate needs config first.
                validate_repository(folder, current, scan=scan, tolerate=(FailureCodes.NO_HEADER,))
                validate_config_change(current, new_config, folder, target=target, scan=scan, warnings=warnings)

            # Creating the new folder here, BEFORE the config commits,
            # means a failure creating it aborts cleanly with nothing yet
            # written -- committing folderadr to disk first instead would
            # leave the repository pointing at a directory that didn't
            # exist, with no `data` naming that already-committed change,
            # and every subsequent command failing with a generic io-error
            # until someone noticed and retried. The folders are left
            # if the write below still somehow fails afterward -- an
            # unused empty folder, not a real cost.
            new_folder = resolve_within(target, new_config.folderadr)
            created.append((new_folder, make_dirs(new_folder)))
            # Before the write, so nothing that can fail runs once the
            # config is on disk.
            preview = None
            if "migrationpattern" in flags and new_config.migrationpattern:
                preview = legacy_pattern_preview(scan_tree(new_folder).markdown, new_config)
                warnings.extend(legacy_pattern_warnings(preview, PATTERN_ADVICE_BEFORE_MIGRATE))
        except BaseException:
            for created_folder, top in reversed(created):
                remove_created_dirs(created_folder, top)
            raise

        attempts = atomic_write_text(config_path, merged_text)
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    result = {"file": str(config_path), "updated_fields": updated_fields, "warnings": warnings}
    if preview is not None:
        result["migrationpattern_preview"] = preview
    return result
