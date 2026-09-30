"""Repository configuration schema: the single source of
truth for a repo's `.adrpy.json`. Always read live from disk,
never cached across invocations, so a command never works from a stale
copy of the file.

ADR0007V01: `folderlog` has a computed default instead of being required
(see `parse_repo_config`), so an `.adrpy.json` without it still parses.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from adrpy.core.casing import CASE_TRANSFORMS
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.fs import read_bounded, read_with_permission_retry
from adrpy.core.notices import notice
from adrpy.core.naming import migration_pattern_overlap, parse_migration_pattern
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_marker_comment_syntax,
    reject_status_marker_forgery_characters,
)

VALID_SEPARATORS = ("-", "_", ".")
VALID_CASE_TRANSFORMS = tuple(CASE_TRANSFORMS.keys())

# Bounds on these three fields: nothing but this schema guards a value
# edited by hand, and a digit count outside them makes names no reader
# wants (lenseq 7+) or none at all (lenversion 0).
LENSEQ_MIN, LENSEQ_MAX = 3, 6
LENVERSION_MIN, LENVERSION_MAX = 2, 4
LENREVISION_MIN, LENREVISION_MAX = 0, 3

# ADR0005V01: the one definition of the 3 int fields' bounds, also used by
# `cli/config.py` and `cli/installconfig.py`.
INT_FIELD_BOUNDS = {
    "lenseq": (LENSEQ_MIN, LENSEQ_MAX),
    "lenversion": (LENVERSION_MIN, LENVERSION_MAX),
    "lenrevision": (LENREVISION_MIN, LENREVISION_MAX),
}

# The length bounds below keep every field fit for the one-line header
# cell or file name it becomes. `prefix`'s charset restriction is a
# correctness requirement, not cosmetic: core/naming.py's filename parser
# assumes the prefix segment is letters-only to tell it apart from the
# digit run that follows.
PREFIX_MAX_LENGTH = 5
_PREFIX_PATTERN = re.compile(rf"^[A-Za-z]{{0,{PREFIX_MAX_LENGTH}}}$")

REPO_CONFIG_NAME = ".adrpy.json"  # at the repository root; what makes a folder a repository

FOLDERADR_MAX_LENGTH = 50
FOLDERLOG_MAX_LENGTH = 50  # ADR0007V01: the same bound as folderadr's
HEADER_DISCLAIMER_MAX_LENGTH = 100
HEADER_LABEL_MAX_LENGTH = 40
STATUS_LABEL_MAX_LENGTH = 25
# The template is free-form body content, not a one-line cell: bounded
# so read_config_text's fixed byte cap never rejects a legitimate, if
# unusually long, template.
TEMPLATE_MAX_LENGTH = 10_000

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

# ADR0005V01: each of these 15 codes is a real FailureCodes attribute,
# looked up here rather than formatted from the field name, so the
# registry lists every code this module can raise.
_TOO_LONG_CODES = {
    "headertitlefile": FailureCodes.CONFIG_HEADERTITLEFILE_TOO_LONG,
    "headerversion": FailureCodes.CONFIG_HEADERVERSION_TOO_LONG,
    "headerrevision": FailureCodes.CONFIG_HEADERREVISION_TOO_LONG,
    "headerscope": FailureCodes.CONFIG_HEADERSCOPE_TOO_LONG,
    "headerdomain": FailureCodes.CONFIG_HEADERDOMAIN_TOO_LONG,
    "headertitlestatuscreated": FailureCodes.CONFIG_HEADERTITLESTATUSCREATED_TOO_LONG,
    "headertitlestatuschanged": FailureCodes.CONFIG_HEADERTITLESTATUSCHANGED_TOO_LONG,
    "headertitlestatussuperseded": FailureCodes.CONFIG_HEADERTITLESTATUSSUPERSEDED_TOO_LONG,
    "headertablefields": FailureCodes.CONFIG_HEADERTABLEFIELDS_TOO_LONG,
    "headertablevalues": FailureCodes.CONFIG_HEADERTABLEVALUES_TOO_LONG,
    "headermigrated": FailureCodes.CONFIG_HEADERMIGRATED_TOO_LONG,
    "statusnew": FailureCodes.CONFIG_STATUSNEW_TOO_LONG,
    "statusacc": FailureCodes.CONFIG_STATUSACC_TOO_LONG,
    "statusrej": FailureCodes.CONFIG_STATUSREJ_TOO_LONG,
    "statussup": FailureCodes.CONFIG_STATUSSUP_TOO_LONG,
}

# ADR0008V01: every code parse_repo_config can raise, one static one-line
# condition each -- reachable from every command (parse_repo_config runs
# on every invocation's own config load, via resolve_target_and_config/
# load_repo_config), so each command's own describe() merges this dict
# into its own failure_codes field rather than repeating the same 40
# entries by hand. Excludes language-not-supported (core/config.py's
# own load_language_pack, only reachable via --language on init/
# installconfig, not universal).
SHARED_FAILURE_CODES = {
    FailureCodes.CONFIG_FILE_TOO_LARGE: "The config file exceeds the 64KB size limit.",
    FailureCodes.CONFIG_FILE_EMPTY: "The repository's .adrpy.json is empty (0 bytes), most likely left by an interrupted init: remove it and run init again.",
    FailureCodes.CONFIG_INVALID_ENCODING: "The config file's bytes are not valid UTF-8.",
    FailureCodes.CONFIG_INVALID_JSON: "The config file is not valid JSON, or its root is not a JSON object.",
    FailureCodes.CONFIG_MISSING_FIELD: "The config is missing one or more required fields.",
    FailureCodes.CONFIG_UNEXPECTED_FIELD: "The config has one or more fields this schema does not recognize.",
    FailureCodes.CONFIG_WRONG_TYPE: "A field's value is not the type this schema requires for it (string/integer).",
    FailureCodes.CONFIG_LENSEQ_TOO_SMALL: f"lenseq is below its configured minimum ({LENSEQ_MIN}).",
    FailureCodes.CONFIG_LENSEQ_TOO_LARGE: f"lenseq is above its configured maximum ({LENSEQ_MAX}).",
    FailureCodes.CONFIG_LENVERSION_TOO_SMALL: f"lenversion is below its configured minimum ({LENVERSION_MIN}).",
    FailureCodes.CONFIG_LENVERSION_TOO_LARGE: f"lenversion is above its configured maximum ({LENVERSION_MAX}).",
    FailureCodes.CONFIG_LENREVISION_NEGATIVE: f"lenrevision is below its configured minimum ({LENREVISION_MIN}).",
    FailureCodes.CONFIG_LENREVISION_TOO_LARGE: f"lenrevision is above its configured maximum ({LENREVISION_MAX}).",
    FailureCodes.CONFIG_SEPARATOR_INVALID: f"separator is not one of {VALID_SEPARATORS}.",
    FailureCodes.CONFIG_CASETRANSFORM_INVALID: "casetransform is not one of the recognized case-transform names.",
    FailureCodes.CONFIG_FIELD_EMPTY: "A field that must be non-empty is an empty string.",
    FailureCodes.CONFIG_PREFIX_INVALID: f"prefix is not ASCII letters only, max {PREFIX_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_FOLDERADR_TOO_LONG: f"folderadr exceeds {FOLDERADR_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_FOLDERADR_NOT_RELATIVE: "folderadr is absolute, drive-relative, a UNC path, or leads outside the repository (..) -- it must be a relative path inside it.",
    FailureCodes.CONFIG_FOLDERLOG_TOO_LONG: f"folderlog exceeds {FOLDERLOG_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_FOLDERLOG_NOT_RELATIVE: "folderlog is absolute, drive-relative, a UNC path, or leads outside the repository (..) -- it must be a relative path inside it.",
    FailureCodes.CONFIG_FOLDERADR_FOLDERLOG_OVERLAP: "folderadr and folderlog are the same directory, or one is nested inside the other.",
    FailureCodes.CONFIG_TEMPLATE_TOO_LONG: f"template exceeds {TEMPLATE_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERDISCLAIMER_TOO_LONG: f"headerdisclaimer exceeds {HEADER_DISCLAIMER_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_FIELD_IS_BLANK: "A field is non-empty but blank after stripping whitespace.",
    FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER: "A field contains '|' or a line-break-like character (or, for the 4 status labels, '(', ')', '<!--', '-->', or ':'; or, for headertablefields/headertablevalues, '<!--' or '-->').",
    FailureCodes.CONFIG_MIGRATIONPATTERN_INVALID: "migrationpattern is non-empty but does not match N##:##T##[V##:##][R##:##][P##:##]; or, where a migrationpattern is set (config, installconfig, init, explore's preview) and at migrate, its T starts inside its N/V/R/P range or two of those ranges overlap (the detail names the overlap).",
    FailureCodes.CONFIG_HEADERTITLEFILE_TOO_LONG: f"headertitlefile exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERVERSION_TOO_LONG: f"headerversion exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERREVISION_TOO_LONG: f"headerrevision exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERSCOPE_TOO_LONG: f"headerscope exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERDOMAIN_TOO_LONG: f"headerdomain exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERTITLESTATUSCREATED_TOO_LONG: f"headertitlestatuscreated exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERTITLESTATUSCHANGED_TOO_LONG: f"headertitlestatuschanged exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERTITLESTATUSSUPERSEDED_TOO_LONG: f"headertitlestatussuperseded exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERTABLEFIELDS_TOO_LONG: f"headertablefields exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERTABLEVALUES_TOO_LONG: f"headertablevalues exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_HEADERMIGRATED_TOO_LONG: f"headermigrated exceeds {HEADER_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_STATUSNEW_TOO_LONG: f"statusnew exceeds {STATUS_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_STATUSACC_TOO_LONG: f"statusacc exceeds {STATUS_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_STATUSREJ_TOO_LONG: f"statusrej exceeds {STATUS_LABEL_MAX_LENGTH} characters.",
    FailureCodes.CONFIG_STATUSSUP_TOO_LONG: f"statussup exceeds {STATUS_LABEL_MAX_LENGTH} characters.",
}


def _is_relative_path(value):
    """Rejects anything that could anchor outside the repository on either
    platform, not just what looks absolute on the host OS: a POSIX-absolute
    path, a Windows-absolute path, a Windows drive-relative reference
    (`C:foo`, which PureWindowsPath does NOT consider absolute but which
    still anchors to a specific drive's own current directory), and a UNC
    path -- a hostile config (e.g. from a cloned repo) must never be able to
    point folderadr outside the repo via `init`/`new`/etc. A leading `\`
    too: rooted at the current drive on Windows, with no drive letter."""
    if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
        return False
    if re.match(r"^[A-Za-z]:", value) or value.startswith(("\\", "//")):
        return False
    return True


def _stays_inside(value):
    """Whether `value` never climbs above its starting folder, read
    lexically both ways: with `\\` as a separator (Windows) and as part of
    a name (POSIX, where `a\\b/../../x` escapes). `doc/../log` stays,
    `doc/../../x` does not. resolve_within still resolves links when the
    folder is used."""
    for parts in (PureWindowsPath(value).parts, PurePosixPath(value).parts):
        depth = 0
        for part in parts:
            depth += -1 if part == ".." else 0 if part == "." else 1
            if depth < 0:
                return False
    return True


def _normalized_repo_path_parts(value):
    """THIS host's view of `value`'s path components (native separator,
    `.`/`..` collapsed via os.path.normpath, each component case-folded),
    for the folderadr/folderlog overlap comparison ONLY: the stored value
    stays exactly as the config text gave it (forward slashes). Without
    this, a `../` traversal, a backslash-separated nesting on Windows, or
    a case difference could name the same or a nested directory while
    comparing unequal as raw strings."""
    return tuple(part.casefold() for part in Path(os.path.normpath(value)).parts)


def _validate_relative_repo_path_field(value, field_name, max_length, too_long_code, not_relative_code):
    """Shared by folderadr and folderlog (ADR0007V01): the same length and
    escape-path validation, with each field's own max length and failure
    codes."""
    if len(value) > max_length:
        raise CommandError(too_long_code, f"{field_name} must be <= {max_length} characters.")
    if not _is_relative_path(value) or not _stays_inside(value):
        raise CommandError(
            not_relative_code,
            f"{field_name} must be a relative path inside the repository (a hostile config must never point "
            "outside it).",
        )


_STRING_FIELDS = (
    "folderadr",
    "folderlog",
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
ALL_FIELDS = _STRING_FIELDS + _INT_FIELDS
# Fields a config may still hold but no longer has: dropped on read with a
# warning, and gone from the file at its next write.
_RETIRED_FIELDS = ("activeplugins", "disableplugins")

# migrationpattern, template and prefix may be empty; every other string
# field may not.
_NON_EMPTY_STRING_FIELDS = tuple(
    name for name in _STRING_FIELDS if name not in ("migrationpattern", "template", "prefix")
)


@dataclass
class RepoConfig:
    folderadr: str
    folderlog: str
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


def serialize_repo_config(fields):
    """The one JSON form .adrpy.json is written in (init, config,
    migrate's migrationpattern persist-back): `fields` (a RepoConfig's
    asdict, in schema order) with a 2-space indent and non-ASCII
    characters kept as they are -- so a later change rewrites only its
    own lines."""
    return json.dumps(fields, indent=2, ensure_ascii=False)


def load_repo_config(path):
    text = read_config_text(path)
    if text == "":
        raise_config_file_empty(path)
    return parse_repo_config(text)


def raise_config_file_empty(path):
    """A 0-byte .adrpy.json: what an init interrupted after
    reserving the name leaves on a filesystem without hard links."""
    raise CommandError(
        FailureCodes.CONFIG_FILE_EMPTY,
        f"{path} is empty (0 bytes), most likely left by an interrupted init: remove it and run adrpy init again.",
        data={"file": str(path)},
    )


def default_repo_config_text():
    """The bundled, built-in default -- `init`'s last-resort fallback (no
    --seed, no --language, no install-level config), and the one reader
    of this resource wherever the built-in default is shown or seeded."""
    from importlib import resources

    resource = resources.files("adrpy.resources").joinpath("default_repo_config.json")
    return resource.read_text(encoding="utf-8")


# `language` doesn't just affect interactive UI text -- it also selects
# the DEFAULT header/status labels and the default template content a
# language-pack shortcut seeds (`init`, `installconfig`).
SUPPORTED_LANGUAGES = (
    "en-us",
    "pt-br",
    "de-de",
    "es-es",
    "fr-fr",
    "it-it",
    "ja-jp",
    "ko-kr",
    "nl-be",
    "ru-ru",
    "zh-cn",
)


def load_language_pack(language):
    """Returns a language pack's own ~17 fields (header/status labels +
    the default template) as a dict, or raises language-not-supported if
    `language` isn't one of SUPPORTED_LANGUAGES."""
    if language not in SUPPORTED_LANGUAGES:
        raise CommandError(
            FailureCodes.LANGUAGE_NOT_SUPPORTED, f"--language must be one of {SUPPORTED_LANGUAGES}, got: {language}"
        )
    from importlib import resources

    resource = resources.files("adrpy.resources.language_packs").joinpath(f"{language}.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def default_repo_config_text_for_language(language):
    """Merges a language pack's ~17 fields onto the built-in default --
    everything else (folderadr, separator, lenseq/lenversion/lenrevision,
    casetransform, migrationpattern) is language-independent, so it keeps
    the same built-in default regardless of `language`."""
    base = json.loads(default_repo_config_text())
    base.update(load_language_pack(language))
    return json.dumps(base, indent=2, ensure_ascii=False)


# Read on every command invocation (the repository's config load), plus
# init/installconfig --seed: with no size cap, a 150MB config file
# measured a ~300MB peak-memory read. 64KB is generous: every
# length-bounded field (TEMPLATE_MAX_LENGTH exists to make this cap safe)
# summed at its maximum, JSON-escaped, stays well under it. Deliberately
# NOT configurable -- the cap cannot come from the config it bounds.
CONFIG_READ_MAX_BYTES = 65536
_CONFIG_READ_CHUNK_SIZE = 4096


def read_config_text(path):
    """Shared by every reader of a config JSON file (the repo's
    .adrpy.json, init's --seed): invalid bytes become a structured
    CommandError, not a raw UnicodeDecodeError with empty stdout. Bounded
    to CONFIG_READ_MAX_BYTES: raises config-file-too-large instead of
    reading further when the real file exceeds it.

    Retries a transient PermissionError like every other read
    (core/fs.read_with_permission_retry): the file is replaced through the
    same atomic_write_text -> os.replace path those retries absorb, and
    this read runs for every command, mostly BEFORE any attach_warnings
    safety net is entered."""
    try:
        raw_bytes = read_with_permission_retry(
            lambda: read_bounded(path, CONFIG_READ_MAX_BYTES, _CONFIG_READ_CHUNK_SIZE)
        )
        if len(raw_bytes) > CONFIG_READ_MAX_BYTES:
            raise CommandError(
                FailureCodes.CONFIG_FILE_TOO_LARGE,
                f"{path}: exceeds the {CONFIG_READ_MAX_BYTES}-byte config file size limit.",
            )
        # Universal-newline translation, as Path.read_text does: JSON
        # parsing does not need it, but read_install_config_text passes
        # this text through to its callers.
        return raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as error:
        raise CommandError(FailureCodes.CONFIG_INVALID_ENCODING, f"{path}: {error}") from error


def parse_repo_config(text):
    try:
        raw = json.loads(text)
    except (ValueError, RecursionError) as error:
        # ValueError covers JSONDecodeError and an integer past Python's
        # digit limit; RecursionError, nesting too deep to decode. Each is a
        # config that is not usable JSON -- a stable code, never an internal
        # error. installconfig --seed/--language replace such an install-level
        # config; a repository's is repaired by hand (init and config run the
        # change guards against the current file, so they cannot).
        raise CommandError(
            FailureCodes.CONFIG_INVALID_JSON,
            f"{error} -- the file is not valid JSON: repair it by hand (the install-level config can also be "
            "replaced with `adrpy installconfig --seed` or `--language`).",
        ) from error

    if not isinstance(raw, dict):
        raise CommandError(FailureCodes.CONFIG_INVALID_JSON, "Configuration root must be a JSON object.")

    retired = [key for key in raw if key.lower() in _RETIRED_FIELDS]
    if retired:
        notice(f"{', '.join(retired)}: no longer config field(s); ignored, and removed when `adrpy config` or `adrpy installconfig` next writes that file.")
    lowered = {key.lower(): value for key, value in raw.items() if key.lower() not in _RETIRED_FIELDS}

    missing = [name for name in ALL_FIELDS if name != "folderlog" and name not in lowered]
    if missing:
        raise CommandError(FailureCodes.CONFIG_MISSING_FIELD, f"Missing required field(s): {', '.join(missing)}")

    extra = [key for key in raw if key.lower() not in ALL_FIELDS + _RETIRED_FIELDS]
    if extra:
        raise CommandError(FailureCodes.CONFIG_UNEXPECTED_FIELD, f"Unexpected field(s): {', '.join(extra)}")

    # ADR0007V01: folderlog defaults to the exact computed sibling-of-
    # folderadr location when absent, so an .adrpy.json written
    # before this field existed keeps parsing unchanged. Guarded against a
    # non-string folderadr (not yet type-checked at this point) so this
    # never raises an uncaught TypeError instead of the real
    # config-wrong-type error the loop right below already reports for it.
    if "folderlog" not in lowered:
        folderadr_value = lowered.get("folderadr")
        lowered["folderlog"] = (
            str(PurePosixPath(folderadr_value).parent / "decision-log")
            if isinstance(folderadr_value, str)
            else ""
        )

    for name in _STRING_FIELDS:
        if not isinstance(lowered[name], str):
            raise CommandError(FailureCodes.CONFIG_WRONG_TYPE, f"Field '{name}' must be a string.")

    for name in _INT_FIELDS:
        value = lowered[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise CommandError(FailureCodes.CONFIG_WRONG_TYPE, f"Field '{name}' must be an integer.")

    if lowered["lenseq"] < LENSEQ_MIN:
        raise CommandError(FailureCodes.CONFIG_LENSEQ_TOO_SMALL, f"lenseq must be >= {LENSEQ_MIN}.")
    if lowered["lenseq"] > LENSEQ_MAX:
        raise CommandError(FailureCodes.CONFIG_LENSEQ_TOO_LARGE, f"lenseq must be <= {LENSEQ_MAX}.")
    if lowered["lenversion"] < LENVERSION_MIN:
        raise CommandError(FailureCodes.CONFIG_LENVERSION_TOO_SMALL, f"lenversion must be >= {LENVERSION_MIN}.")
    if lowered["lenversion"] > LENVERSION_MAX:
        raise CommandError(FailureCodes.CONFIG_LENVERSION_TOO_LARGE, f"lenversion must be <= {LENVERSION_MAX}.")
    if lowered["lenrevision"] < LENREVISION_MIN:
        raise CommandError(FailureCodes.CONFIG_LENREVISION_NEGATIVE, f"lenrevision must be >= {LENREVISION_MIN}.")
    if lowered["lenrevision"] > LENREVISION_MAX:
        raise CommandError(FailureCodes.CONFIG_LENREVISION_TOO_LARGE, f"lenrevision must be <= {LENREVISION_MAX}.")

    if lowered["separator"] not in VALID_SEPARATORS:
        raise CommandError(FailureCodes.CONFIG_SEPARATOR_INVALID, f"separator must be one of {VALID_SEPARATORS}.")

    if lowered["casetransform"] not in VALID_CASE_TRANSFORMS:
        raise CommandError(
            FailureCodes.CONFIG_CASETRANSFORM_INVALID, f"casetransform must be one of {VALID_CASE_TRANSFORMS}."
        )

    for name in _NON_EMPTY_STRING_FIELDS:
        if lowered[name] == "":
            raise CommandError(FailureCodes.CONFIG_FIELD_EMPTY, f"Field '{name}' cannot be empty.")

    if not _PREFIX_PATTERN.match(lowered["prefix"]):
        raise CommandError(
            FailureCodes.CONFIG_PREFIX_INVALID,
            f"prefix must be ASCII letters only, max {PREFIX_MAX_LENGTH} characters.",
        )

    _validate_relative_repo_path_field(
        lowered["folderadr"],
        "folderadr",
        FOLDERADR_MAX_LENGTH,
        FailureCodes.CONFIG_FOLDERADR_TOO_LONG,
        FailureCodes.CONFIG_FOLDERADR_NOT_RELATIVE,
    )
    _validate_relative_repo_path_field(
        lowered["folderlog"],
        "folderlog",
        FOLDERLOG_MAX_LENGTH,
        FailureCodes.CONFIG_FOLDERLOG_TOO_LONG,
        FailureCodes.CONFIG_FOLDERLOG_NOT_RELATIVE,
    )

    # ADR0007V01: folderadr and folderlog are each scanned recursively, so
    # if either is the same directory as, or nested inside, the other,
    # each scan would see the other's files. Compared via
    # _normalized_repo_path_parts; neither field's STORED value changes.
    folderadr_parts = _normalized_repo_path_parts(lowered["folderadr"])
    folderlog_parts = _normalized_repo_path_parts(lowered["folderlog"])
    shorter, longer = (
        (folderadr_parts, folderlog_parts)
        if len(folderadr_parts) <= len(folderlog_parts)
        else (folderlog_parts, folderadr_parts)
    )
    if longer[: len(shorter)] == shorter:
        raise CommandError(
            FailureCodes.CONFIG_FOLDERADR_FOLDERLOG_OVERLAP,
            f"folderadr ('{lowered['folderadr']}') and folderlog ('{lowered['folderlog']}') must not be the "
            "same directory, or nested inside one another.",
        )

    if len(lowered["template"]) > TEMPLATE_MAX_LENGTH:
        raise CommandError(
            FailureCodes.CONFIG_TEMPLATE_TOO_LONG, f"template must be <= {TEMPLATE_MAX_LENGTH} characters."
        )

    if len(lowered["headerdisclaimer"]) > HEADER_DISCLAIMER_MAX_LENGTH:
        raise CommandError(
            FailureCodes.CONFIG_HEADERDISCLAIMER_TOO_LONG,
            f"headerdisclaimer must be <= {HEADER_DISCLAIMER_MAX_LENGTH} characters.",
        )

    for name in _HEADER_LABEL_FIELDS_MAX_40:
        if len(lowered[name]) > HEADER_LABEL_MAX_LENGTH:
            raise CommandError(
                _TOO_LONG_CODES[name], f"Field '{name}' must be <= {HEADER_LABEL_MAX_LENGTH} characters."
            )

    for name in _STATUS_LABEL_FIELDS:
        if len(lowered[name]) > STATUS_LABEL_MAX_LENGTH:
            raise CommandError(
                _TOO_LONG_CODES[name], f"Field '{name}' must be <= {STATUS_LABEL_MAX_LENGTH} characters."
            )

    # Every one of these lands verbatim in a fixed-position header-table
    # cell (build_header/status rows): an embedded '|' or line-break-like
    # character forges an extra row (e.g. an Accepted status that bypasses
    # approval). The same check as for command arguments
    # (title/scope/domain), reported under config-* codes.
    for name in _HEADER_LABEL_FIELDS_MAX_40 + (_STATUS_LABEL_FIELDS + ("headerdisclaimer",)):
        try:
            reject_embedded_delimiter(lowered[name], name)
        except CommandError as error:
            if error.code == FailureCodes.FIELD_IS_BLANK:
                raise CommandError(FailureCodes.CONFIG_FIELD_IS_BLANK, error.detail) from error
            raise CommandError(FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER, error.detail) from error

    # ADR0004V01's hidden canonical marker (`<!-- Status -->` after the status
    # cell's parenthesized date) is only trustworthy if a status LABEL can
    # never itself contain the characters that mark a date/marker boundary --
    # otherwise a hostile statusnew/statusacc/statusrej/statussup forges a
    # marker and date the tool never wrote (e.g. a label of
    # "(20200101)<!--Rejected-->" makes a decision created today read back
    # as Rejected/2020-01-01). Scoped to just these four fields, since no other
    # field is read by _parse_status_cell this way.
    for name in _STATUS_LABEL_FIELDS:
        try:
            reject_status_marker_forgery_characters(lowered[name], name)
        except CommandError as error:
            raise CommandError(FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER, error.detail) from error

    # parse_header's own is_migrated detection (core/header.py) is pure
    # substring matching for an HTML-comment-shaped tail on the row these
    # two fields build -- a hostile '<!--'/'-->' in either one forges
    # is_migrated=True on every ordinary file's header.
    for name in ("headertablefields", "headertablevalues"):
        try:
            reject_marker_comment_syntax(lowered[name], name)
        except CommandError as error:
            raise CommandError(FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER, error.detail) from error

    migrationpattern = lowered["migrationpattern"]
    if migrationpattern and parse_migration_pattern(migrationpattern) is None:
        raise CommandError(
            FailureCodes.CONFIG_MIGRATIONPATTERN_INVALID,
            "migrationpattern must match N##:##T##[V##:##][R##:##][P##:##], e.g. 'N00:04T04'.",
        )

    return RepoConfig(**{name: lowered[name] for name in ALL_FIELDS})


def reject_overlapping_migration_pattern(pattern_text):
    """config-migrationpattern-invalid when `pattern_text` reads part of a
    name twice (core/naming.migration_pattern_overlap). Called where a
    migrationpattern is set and by migrate, deliberately not by
    parse_repo_config: a repository whose config already holds such a
    pattern (possibly with decisions migrated under it) must still load,
    and the pattern guard would otherwise leave it unable to change."""
    overlap = migration_pattern_overlap(pattern_text)
    if overlap is not None:
        raise CommandError(
            FailureCodes.CONFIG_MIGRATIONPATTERN_INVALID,
            f"migrationpattern '{pattern_text}' reads part of a name twice: {overlap}. For `0001-title.md`, "
            "'N00:04T05' reads number 0001 and title 'title'.",
        )
