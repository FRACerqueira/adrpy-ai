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
from adrpy.core.config import _INT_FIELDS, _STRING_FIELDS, load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError

_BOOLEAN_FIELD_FLAGS = ("disableplugins",)
_EDITABLE_FIELDS = _STRING_FIELDS + _INT_FIELDS + _BOOLEAN_FIELD_FLAGS


def describe():
    return {
        "name": "config",
        "description": "Updates fields of an existing repository's adr-config.adrplus. Omitted fields keep their current value.",
        "arguments": [
            {"name": "path", "type": "string", "required": True, "description": "Repository root directory."},
            *[
                {"name": field, "type": "string", "required": False, "description": f"New value for '{field}'."}
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

    merged_text = json.dumps(merged, indent=2, ensure_ascii=False)
    parse_repo_config(merged_text)  # re-validates the merged result; raises on failure

    atomic_write_text(config_path, merged_text)

    return {"file": str(config_path), "updated_fields": updated_fields}
