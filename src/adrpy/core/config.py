"""Repository configuration schema (harness Fase 3): the single source of
truth for a repo's `adr-config.adrplus`, byte-compatible with AdrPlus's own
schema (AdrPlusRepoConfig.cs / ValidateConfig.ValidateRepoStructure) -- no
field is ever added to it. Always read live from disk, never cached across
invocations, so the two tools never see a stale copy of each other's writes.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from adrpy.core.errors import CommandError

VALID_SEPARATORS = ("-", "_", ".")
VALID_CASE_TRANSFORMS = ("CamelCase", "PascalCase", "SnakeCase", "KebabCase")

# Upper bounds are a deliberate divergence from the original, not fidelity:
# AdrPlus's real non-interactive validator (ValidateConfig.
# ValidateConfigRepoFieldValues) has no maximum at all for these three
# fields -- only its interactive `config --wizard` slider limits them
# (lenseq 3-5, lenversion 2-3, lenrevision 0-3, see PromptConsole.cs's
# PromptEditFieldLenSeq/Revision/Version), and hand-editing the config file
# (or `config --repository --file`) bypasses that slider entirely even in
# the original. Without a wizard here, nothing else would ever guard these
# values, so this project adds them explicitly -- confirmed with the user,
# who chose slightly wider bounds than the wizard's own.
LENSEQ_MIN, LENSEQ_MAX = 3, 6
LENVERSION_MIN, LENVERSION_MAX = 2, 4
LENREVISION_MIN, LENREVISION_MAX = 0, 3

_STRING_FIELDS = (
    "folderadr",
    "migrationpattern",
    "template",
    "prefix",
    "separator",
    "casetransform",
    "statusnew",
    "statusacc",
    "statusrej",
    "statussup",
    "headerdisclaimer",
    "headertitlefile",
    "headerversion",
    "headerrevision",
    "headerscope",
    "headerdomain",
    "headertitlestatuscreated",
    "headertitlestatuschanged",
    "headertitlestatussuperseded",
    "headertablefields",
    "headertablevalues",
    "headermigrated",
)
_INT_FIELDS = ("lenseq", "lenversion", "lenrevision")
_BOOL_FIELDS = ("disableplugins",)
_LIST_FIELDS = ("activeplugins",)
ALL_FIELDS = _STRING_FIELDS + _INT_FIELDS + _BOOL_FIELDS + _LIST_FIELDS

# migrationpattern and template have no "cannot be empty" rule of their own;
# every other string field does (ValidateConfigRepoFieldValues in the C#).
_NON_EMPTY_STRING_FIELDS = tuple(
    name for name in _STRING_FIELDS if name not in ("migrationpattern", "template", "prefix")
)


@dataclass
class RepoConfig:
    folderadr: str
    migrationpattern: str
    template: str
    prefix: str
    lenseq: int
    lenversion: int
    lenrevision: int
    separator: str
    casetransform: str
    statusnew: str
    statusacc: str
    statusrej: str
    statussup: str
    headerdisclaimer: str
    headertitlefile: str
    headerversion: str
    headerrevision: str
    headerscope: str
    headerdomain: str
    headertitlestatuscreated: str
    headertitlestatuschanged: str
    headertitlestatussuperseded: str
    headertablefields: str
    headertablevalues: str
    headermigrated: str
    activeplugins: list
    disableplugins: bool


def load_repo_config(path):
    text = Path(path).read_text(encoding="utf-8")
    return parse_repo_config(text)


def parse_repo_config(text):
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError("config-invalid-json", str(error)) from error

    if not isinstance(raw, dict):
        raise CommandError("config-invalid-json", "Configuration root must be a JSON object.")

    lowered = {key.lower(): value for key, value in raw.items()}

    missing = [name for name in ALL_FIELDS if name not in lowered]
    if missing:
        raise CommandError("config-missing-field", f"Missing required field(s): {', '.join(missing)}")

    extra = [key for key in raw if key.lower() not in ALL_FIELDS]
    if extra:
        raise CommandError("config-unexpected-field", f"Unexpected field(s): {', '.join(extra)}")

    for name in _STRING_FIELDS:
        if not isinstance(lowered[name], str):
            raise CommandError("config-wrong-type", f"Field '{name}' must be a string.")

    for name in _INT_FIELDS:
        value = lowered[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise CommandError("config-wrong-type", f"Field '{name}' must be an integer.")

    for name in _BOOL_FIELDS:
        if not isinstance(lowered[name], bool):
            raise CommandError("config-wrong-type", f"Field '{name}' must be a boolean.")

    for name in _LIST_FIELDS:
        value = lowered[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CommandError("config-wrong-type", f"Field '{name}' must be an array of strings.")

    if lowered["lenseq"] < LENSEQ_MIN:
        raise CommandError("config-lenseq-too-small", f"lenseq must be >= {LENSEQ_MIN}.")
    if lowered["lenseq"] > LENSEQ_MAX:
        raise CommandError("config-lenseq-too-large", f"lenseq must be <= {LENSEQ_MAX}.")
    if lowered["lenversion"] < LENVERSION_MIN:
        raise CommandError("config-lenversion-too-small", f"lenversion must be >= {LENVERSION_MIN}.")
    if lowered["lenversion"] > LENVERSION_MAX:
        raise CommandError("config-lenversion-too-large", f"lenversion must be <= {LENVERSION_MAX}.")
    if lowered["lenrevision"] < LENREVISION_MIN:
        raise CommandError("config-lenrevision-negative", f"lenrevision must be >= {LENREVISION_MIN}.")
    if lowered["lenrevision"] > LENREVISION_MAX:
        raise CommandError("config-lenrevision-too-large", f"lenrevision must be <= {LENREVISION_MAX}.")

    if lowered["separator"] not in VALID_SEPARATORS:
        raise CommandError("config-separator-invalid", f"separator must be one of {VALID_SEPARATORS}.")

    if lowered["casetransform"] not in VALID_CASE_TRANSFORMS:
        raise CommandError(
            "config-casetransform-invalid", f"casetransform must be one of {VALID_CASE_TRANSFORMS}."
        )

    for name in _NON_EMPTY_STRING_FIELDS:
        if lowered[name] == "":
            raise CommandError("config-field-empty", f"Field '{name}' cannot be empty.")

    # migrationpattern's own format (when non-empty) is validated in Fase 6,
    # once the legacy-scheme parser it depends on exists.

    return RepoConfig(**{name: lowered[name] for name in ALL_FIELDS})
