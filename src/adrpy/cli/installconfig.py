"""`installconfig` command: reads or updates the per-user install-level
config (ADR002V01 -- not a port of anything in the reference tool,
which stores its own equivalent relative to its own install directory
instead; see the ADR for why that storage location was not mirrored
here).

Unlike every other command, this one takes no `--path` -- it always
operates on the one, fixed, per-user location `core/install_config.py`
resolves (`%APPDATA%\\adrpy\\install-config.json` on Windows,
`$XDG_CONFIG_HOME/adrpy/install-config.json` or
`~/.config/adrpy/install-config.json` on POSIX -- also always returned
as this command's own `file` key, so a caller never needs to know the
convention to locate it). One flag per schema field (mirroring
`config`'s own pattern),
plus `--seed <file>` for bulk setup or import -- and since this file's
schema is byte-compatible with a repository's own adr-config.adrplus
(ADR002V01), `--seed` pointed directly at a real installation of the
reference tool's own template file already covers importing from it; no separate
cross-tool flag, and no knowledge of the reference tool's own install-
directory layout, is added for that.

`activeplugins` is deliberately not exposed here either, same as
`config` -- the plugin system is out of scope (see the `init` command's
own note); it is still carried through from whatever base this command
merges onto (the existing file, or the bundled default), never dropped.

Deliberately unlocked: this file is per-user, per-machine state, never
the shared repository state ADR001's lock rule is scoped to (ADR002V01).
A lost update between two concurrent `installconfig` calls is an
accepted, undefended race -- this command is expected to run rarely, by
a single human/agent doing one-time setup, not the routine concurrent
workload the repository lock exists to protect. Confirmed the worst
case really is a lost update, never corruption (a merge-write always
merges onto a fully-committed prior
state, and atomic_write_text's own os.replace-based commit means a
concurrent reader never observes a partial file) -- but the blast
radius of a lost update can be larger than "one field": a `--seed`
(wholesale replace) racing a field-edit (which reads the *existing*
file as its own base, never the seed's content) can have its entire
replacement silently reverted back to the pre-seed file, with only the
field-edit's own one field actually surviving, if the field-edit's
write lands after the seed's.
"""

import json
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core import config as config_schema
from adrpy.core.config import _BOOL_FIELDS, _INT_FIELDS, _STRING_FIELDS, parse_repo_config, read_config_text
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.install_config import resolve_install_config_path
from adrpy.core.warnings import retry_warning

_EDITABLE_FIELDS = _STRING_FIELDS + _INT_FIELDS + _BOOL_FIELDS


def _field_type(field):
    if field in _INT_FIELDS:
        return "integer"
    if field in _BOOL_FIELDS:
        return "boolean"
    return "string"


_INT_FIELD_BOUNDS = {
    "lenseq": (config_schema.LENSEQ_MIN, config_schema.LENSEQ_MAX),
    "lenversion": (config_schema.LENVERSION_MIN, config_schema.LENVERSION_MAX),
    "lenrevision": (config_schema.LENREVISION_MIN, config_schema.LENREVISION_MAX),
}


def _field_description(field):
    """Deliberately duplicated from `config`'s own `_field_description`,
    not shared: most of this function's body is a record of `config`'s
    own flag surface and its own escape hatch (`init --seed`) -- for
    this command the escape hatch is `installconfig --seed` instead, a
    different sentence, not a shared constant. Sharing the function would
    make this command's own `help` output describe the wrong flag."""
    if field == "folderadr":
        return (
            "Relative path to the decisions folder that a newly init'd repository using this as its "
            f"seed will get by default, max {config_schema.FOLDERADR_MAX_LENGTH} characters; cannot be "
            "empty or absolute. Unlike the `config` command's own --folderadr, this one does NOT check "
            "whether the value would escape a repository once applied -- there is no repository yet at "
            "the point this file is written; that check happens later, in whichever command consumes "
            "this file as a seed (currently `init`)."
        )
    if field == "migrationpattern":
        return (
            "Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' "
            "(N##:##T##[V##:##][R##:##][P##:##]); the stored value may be empty, but this flag can't set "
            "it to an empty string here (parse_flags rejects any empty optional value outright) -- use "
            "`installconfig --seed` for that."
        )
    if field == "template":
        return (
            "Default template content a newly init'd repository using this as its seed will get; the "
            "stored value may be empty, but this flag can't set it to an empty string here (parse_flags "
            "rejects any empty optional value outright) -- use `installconfig --seed` for that."
        )
    if field == "prefix":
        return (
            f"ASCII letters only, max {config_schema.PREFIX_MAX_LENGTH} characters; the stored value may "
            "be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty "
            "optional value outright) -- use `installconfig --seed` for that."
        )
    if field == "separator":
        return f"One of {config_schema.VALID_SEPARATORS}."
    if field == "casetransform":
        return f"One of {config_schema.VALID_CASE_TRANSFORMS}."
    if field in config_schema._STATUS_LABEL_FIELDS:
        return (
            f"Status label shown in the header table, max {config_schema.STATUS_LABEL_MAX_LENGTH} "
            "characters; cannot be empty, contain '|', or contain a line-break-like character."
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
    # Same fail-loud guard as config.py's own _field_description, and for
    # the same reason: a newly added schema field with no matching branch
    # here must be caught immediately, not silently fall through to a
    # tautological message.
    raise AssertionError(f"No description defined for editable field '{field}'.")


def _default_config_text():
    resource = resources.files("adrpy.resources").joinpath("default_repo_config.json")
    return resource.read_text(encoding="utf-8")


def describe():
    return {
        "name": "installconfig",
        "description": (
            "Reads or updates the per-user install-level config (ADR002V01) -- used by `init` as its "
            "default seed when no --seed/--language is given, and by `migrate` as a migrationpattern "
            "fallback when a repository's own is empty. Unlike every other command, takes no --path: "
            "always operates on the one, fixed, per-user location this machine resolves to. "
            "With no field flags and no --seed, reads the current config back (read-only, no write); "
            "the result's `configured` key is false with no `config` key at all if the file doesn't "
            "exist yet -- the normal state for any installation that has never run this command, not an "
            "error -- or true with a `config` key otherwise. `updated_fields` is present as an empty "
            "list on every read too, same as `config`'s own bare-read shape -- a generic wrapper that "
            "reads `data.updated_fields` unconditionally works the same after any call, read or write. "
            "`activeplugins` is never included in that read result or accepted as a field to update -- "
            "same as the `config` command, the plugin system is out of scope for now -- but is still "
            "carried through unchanged from whatever base a write merges onto. "
            "Omitted fields keep their current value (or the built-in default's, on first write); only "
            "the fields passed are updated. A write call's result never has the `config`/`configured` "
            "keys. "
            "--seed replaces the file wholesale, same as `init --seed`, and reports every editable field "
            "in `updated_fields` since a full replace makes every one of them this call's own -- not a "
            "diff against whatever was there before."
        ),
        "arguments": [
            {
                "name": "seed",
                "type": "string",
                "required": False,
                "description": (
                    "Path to a config JSON to replace the install-level config with wholesale, instead of "
                    "merging individual field flags -- same semantics as `init --seed`. The install-level "
                    "config's schema is byte-compatible with a repository's own adr-config.adrplus, so "
                    "this also covers importing one from a real installation of the reference tool's own "
                    "template file directly, with no separate flag needed. Any field flag passed ALONGSIDE --seed raises "
                    "usage-error -- pass one or the other -- same as `init`'s own incompatible flag "
                    "combination (--seed with --language)."
                ),
            },
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
    flags = parse_flags(args, optional=("seed",) + _EDITABLE_FIELDS)
    seed_arg = flags.get("seed")
    target = resolve_install_config_path()

    if seed_arg is not None:
        # Decision-log: 2026-09-18--audit-finding--install-config--seed-
        # plus-field-flag-misreports-updated-fields.md -- a co-passed
        # field flag must be rejected outright, matching init's own
        # precedent for its incompatible flag combination (--seed +
        # --language): silently ignoring it while still reporting it in
        # updated_fields would misrepresent what was actually applied.
        conflicting = [field for field in _EDITABLE_FIELDS if field in flags]
        if conflicting:
            raise UsageError(
                f"--seed cannot be combined with field flags ({', '.join(conflicting)}); "
                "pass one or the other."
            )
        seed_path = Path(seed_arg)
        if not seed_path.is_file():
            raise CommandError("config-file-not-found", f"File not found: {seed_arg}")
        seed_text = read_config_text(seed_path)
        parse_repo_config(seed_text)  # validates before writing
        target.parent.mkdir(parents=True, exist_ok=True)
        attempts = atomic_write_text(target, seed_text)
        warning = retry_warning(attempts)
        return {
            "file": str(target),
            "updated_fields": list(_EDITABLE_FIELDS),
            "warnings": [warning] if warning else [],
        }

    if not any(field in flags for field in _EDITABLE_FIELDS):
        if not target.is_file():
            return {"file": str(target), "configured": False, "updated_fields": [], "warnings": []}
        current = parse_repo_config(read_config_text(target))
        current_fields = {field: getattr(current, field) for field in _EDITABLE_FIELDS}
        return {
            "file": str(target),
            "configured": True,
            "config": current_fields,
            "updated_fields": [],
            "warnings": [],
        }

    base_text = read_config_text(target) if target.is_file() else _default_config_text()
    base = parse_repo_config(base_text)
    merged = asdict(base)
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
            raise CommandError("field-not-a-boolean", "--disableplugins must be 'true' or 'false'.")
        merged["disableplugins"] = text == "true"
        updated_fields.append("disableplugins")

    merged_text = json.dumps(merged, indent=2, ensure_ascii=False)
    parse_repo_config(merged_text)  # re-validates the merged result; raises on failure

    target.parent.mkdir(parents=True, exist_ok=True)
    attempts = atomic_write_text(target, merged_text)
    warning = retry_warning(attempts)
    return {"file": str(target), "updated_fields": updated_fields, "warnings": [warning] if warning else []}
