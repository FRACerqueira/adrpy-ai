"""Repository configuration schema: the single source of
truth for a repo's `adr-config.adrplus`, byte-compatible with AdrPlus's
own schema -- no field is ever added to it. Always read live from disk,
never cached across invocations, so the two tools never see a stale copy
of each other's writes.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from adrpy.core.errors import CommandError
from adrpy.core.io_retry import read_with_permission_retry
from adrpy.core.naming import parse_migration_pattern
from adrpy.core.security import reject_embedded_delimiter

VALID_SEPARATORS = ("-", "_", ".")
VALID_CASE_TRANSFORMS = ("CamelCase", "PascalCase", "SnakeCase", "KebabCase")

# Upper bounds are a deliberate divergence, not fidelity: the reference
# tool's own non-interactive validator has no maximum at all for
# these three fields -- only its interactive config wizard's own slider
# limits them (lenseq 3-5, lenversion 2-3, lenrevision 0-3), and
# hand-editing the config file bypasses that slider entirely even there.
# Without a wizard here, nothing else would ever guard these values, so
# this project adds them explicitly -- confirmed with the user, who chose
# slightly wider bounds than the wizard's own.
LENSEQ_MIN, LENSEQ_MAX = 3, 6
LENVERSION_MIN, LENVERSION_MAX = 2, 4
LENREVISION_MIN, LENREVISION_MAX = 0, 3

# Every bound below comes from the same wizard, same reasoning as above.
# `prefix`'s charset restriction is also a real correctness requirement
# here, not just cosmetic: core/naming.py's filename parser assumes the
# prefix segment is letters-only to tell it apart from the digit run that
# follows.
PREFIX_MAX_LENGTH = 5
_PREFIX_PATTERN = re.compile(rf"^[A-Za-z]{{0,{PREFIX_MAX_LENGTH}}}$")

FOLDERADR_MAX_LENGTH = 50  # PromptEditFieldFolderRepo
# headerdisclaimer and status labels: wizard's own real values are 200 and
# 15 (PromptEditFieldHeaderText(headerdisclaimer, 200, ...); PromptEditFieldStatus's
# MaxLength(15)) -- user chose 100/25 instead, same as the lenseq-family bounds.
HEADER_DISCLAIMER_MAX_LENGTH = 100
HEADER_LABEL_MAX_LENGTH = 40  # PromptEditFieldHeaderText(<other header fields>, 40, ...)
STATUS_LABEL_MAX_LENGTH = 25

_HEADER_LABEL_FIELDS_MAX_40 = (
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
_STATUS_LABEL_FIELDS = ("statusnew", "statusacc", "statusrej", "statussup")


def _is_relative_path(value):
    """Rejects anything that could anchor outside the repository on either
    platform, not just what looks absolute on the host OS: a POSIX-absolute
    path, a Windows-absolute path, a Windows drive-relative reference
    (`C:foo`, which PureWindowsPath does NOT consider absolute but which
    still anchors to a specific drive's own current directory), and a UNC
    path -- a hostile config (e.g. from a cloned repo) must never be able to
    point folderadr outside the repo via `init`/`new`/etc."""
    if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
        return False
    if re.match(r"^[A-Za-z]:", value) or value.startswith(("\\\\", "//")):
        return False
    return True

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
# every other string field does.
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
    text = read_config_text(path)
    return parse_repo_config(text)


def read_config_text(path):
    """Shared by every reader of a config JSON file (the repo's own
    adr-config.adrplus, and init's --seed) -- invalid bytes must
    become a structured CommandError, not a raw UnicodeDecodeError with
    empty stdout.

    Retries a transient PermissionError the same way every other read in
    this codebase
    already does (core/lock.py's _read_lock, core/lifecycle.py's
    read_lines_with_report, cli/explore.py's _build_entry) -- this read
    goes through the identical atomic_write_text -> os.replace mechanism
    those retries exist to absorb, and it runs for every single command
    (resolve_repo_and_target's own initial config load), most of it
    BEFORE any lock or attach_warnings safety net is entered."""
    try:
        return read_with_permission_retry(lambda: Path(path).read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise CommandError("config-invalid-encoding", f"{path}: {error}") from error


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

    if not _PREFIX_PATTERN.match(lowered["prefix"]):
        raise CommandError(
            "config-prefix-invalid",
            f"prefix must be ASCII letters only, max {PREFIX_MAX_LENGTH} characters.",
        )

    if len(lowered["folderadr"]) > FOLDERADR_MAX_LENGTH:
        raise CommandError(
            "config-folderadr-too-long", f"folderadr must be <= {FOLDERADR_MAX_LENGTH} characters."
        )

    if not _is_relative_path(lowered["folderadr"]):
        raise CommandError(
            "config-folderadr-not-relative",
            "folderadr must be a relative path (a hostile config must never point outside the repository).",
        )

    if len(lowered["headerdisclaimer"]) > HEADER_DISCLAIMER_MAX_LENGTH:
        raise CommandError(
            "config-headerdisclaimer-too-long",
            f"headerdisclaimer must be <= {HEADER_DISCLAIMER_MAX_LENGTH} characters.",
        )

    for name in _HEADER_LABEL_FIELDS_MAX_40:
        if len(lowered[name]) > HEADER_LABEL_MAX_LENGTH:
            raise CommandError(
                f"config-{name}-too-long", f"Field '{name}' must be <= {HEADER_LABEL_MAX_LENGTH} characters."
            )

    for name in _STATUS_LABEL_FIELDS:
        if len(lowered[name]) > STATUS_LABEL_MAX_LENGTH:
            raise CommandError(
                f"config-{name}-too-long", f"Field '{name}' must be <= {STATUS_LABEL_MAX_LENGTH} characters."
            )

    # Every one of these lands verbatim in a fixed-position header-table
    # cell (build_header/status rows) -- a hostile config that embeds '|'
    # or a line-break-like character here can forge an extra row (confirmed
    # live end-to-end: a forged Accepted status bypassed the approval
    # workflow entirely). Same check already used for live
    # command arguments (title/scope/domain); a config-specific code keeps
    # it consistent with every other config-* validation error.
    for name in _HEADER_LABEL_FIELDS_MAX_40 + (_STATUS_LABEL_FIELDS + ("headerdisclaimer",)):
        try:
            reject_embedded_delimiter(lowered[name], name)
        except CommandError as error:
            raise CommandError("config-field-contains-forbidden-character", error.detail) from error

    # The reference tool validates a non-empty migrationpattern the same way,
    # rejecting anything that doesn't match the
    # N##:##T##[V##:##][R##:##][P##:##] shape.
    migrationpattern = lowered["migrationpattern"]
    if migrationpattern and parse_migration_pattern(migrationpattern) is None:
        raise CommandError(
            "config-migrationpattern-invalid",
            "migrationpattern must match N##:##T##[V##:##][R##:##][P##:##], e.g. 'N00:04T04'.",
        )

    return RepoConfig(**{name: lowered[name] for name in ALL_FIELDS})
