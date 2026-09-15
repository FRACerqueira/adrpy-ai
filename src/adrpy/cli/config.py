"""`config` command: updates fields of an existing repository's own
`adr-config.adrplus` directly (harness Fase 7, item 8 -- reinterpreted per
a confirmed project decision, not a port of ConfigCommandHandler.cs).

Deliberate divergence from the original, escalated and confirmed with the
user: the real `config --repository/--application/--template/--migrate`
never edit an existing repo's own file -- only the interactive wizard (or
`init --file`, which overwrites everything) does. adrpy-ai has no wizard
(Fase 0), so this command exists instead: one flag per config field,
merge/update semantics -- an omitted flag preserves the repo's current
value, never resets it.

`activeplugins` is deliberately not exposed here -- the plugin system is
out of scope for now (confirmed decision). `disableplugins` IS exposed
(it's a meaningful kill-switch field even with no plugins implemented,
harmless either way) but needs an explicit true/false value, not a
presence-only switch, since either direction is a real edit.
"""

import json
from dataclasses import asdict
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core import config as config_schema
from adrpy.core.config import _INT_FIELDS, _STRING_FIELDS, load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.security import resolve_within
from adrpy.core.warnings import retry_warning

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
    """Usability audit M2: cites the same constants core/config.py's own
    validator enforces (never a hand-copied number), so a field's real
    domain is discoverable via `help config` instead of only by
    deliberately triggering the matching config-*-invalid/-too-long
    error -- and the two can never silently drift apart."""
    if field == "folderadr":
        return (
            f"Relative path to the decisions folder, max {config_schema.FOLDERADR_MAX_LENGTH} characters; "
            "cannot be empty, absolute, or escape the repository."
        )
    if field == "migrationpattern":
        return (
            "Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' "
            "(N##:##T##[V##:##][R##:##][P##:##]); may be empty."
        )
    if field == "template":
        return "Default template content for a new decision's body; may be empty."
    if field == "prefix":
        return f"ASCII letters only, max {config_schema.PREFIX_MAX_LENGTH} characters; may be empty."
    if field == "separator":
        return f"One of {config_schema.VALID_SEPARATORS}."
    if field == "casetransform":
        return f"One of {config_schema.VALID_CASE_TRANSFORMS}."
    if field in config_schema._STATUS_LABEL_FIELDS:
        return (
            f"Status label shown in the header table, max {config_schema.STATUS_LABEL_MAX_LENGTH} "
            "characters; cannot be empty."
        )
    if field == "headerdisclaimer":
        return (
            f"Header disclaimer text, max {config_schema.HEADER_DISCLAIMER_MAX_LENGTH} characters; "
            "cannot be empty."
        )
    if field in config_schema._HEADER_LABEL_FIELDS_MAX_40:
        return f"Header row label, max {config_schema.HEADER_LABEL_MAX_LENGTH} characters; cannot be empty."
    if field in _INT_FIELD_BOUNDS:
        low, high = _INT_FIELD_BOUNDS[field]
        return f"Integer between {low} and {high} (inclusive)."
    if field == "disableplugins":
        return "'true' or 'false'."
    return f"New value for '{field}'."


def describe():
    return {
        "name": "config",
        "description": (
            "Reads or updates fields of an existing repository's adr-config.adrplus. "
            "With no field flags, returns the current config unchanged (read-only). "
            "Omitted fields keep their current value; only the fields passed are updated."
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
    target = Path(flags["path"])

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {flags['path']}")

    config_path = target / "adr-config.adrplus"
    if not config_path.is_file():
        raise CommandError("config-not-found", f"No adr-config.adrplus found at: {config_path}")

    current = load_repo_config(config_path)
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

    if not updated_fields:
        # Usability audit A8 + a review of this command's own idempotency:
        # there was no way to read the current config through the JSON
        # contract at all, and calling this with no field flags -- the
        # natural way an agent would try to "just look" -- still rewrote
        # (and reformatted) the file as a side effect of what looks like a
        # read-only call. `activeplugins` stays excluded, same as a write.
        current_fields = {field: merged[field] for field in _EDITABLE_FIELDS}
        return {"file": str(config_path), "updated_fields": [], "config": current_fields, "warnings": []}

    merged_text = json.dumps(merged, indent=2, ensure_ascii=False)
    new_config = parse_repo_config(merged_text)  # re-validates the merged result; raises on failure

    # Fase 5: _is_relative_path only rejects an anchored escape ("C:\..",
    # "\\server\.."); "../../evil" is still relative and passes that check,
    # but resolves outside the repository -- validate before writing, the
    # same order `init` already uses, so a hostile --folderadr can never
    # get persisted and brick the repository (every subsequent command
    # would refuse with path-outside-repository until hand-fixed).
    resolve_within(target, new_config.folderadr)

    attempts = atomic_write_text(config_path, merged_text)
    warnings = []
    warning = retry_warning(attempts)
    if warning:
        warnings.append(warning)

    return {"file": str(config_path), "updated_fields": updated_fields, "warnings": warnings}
