"""Repository configuration schema: the single source of
truth for a repo's `adr-config.adrplus`. Always read live from disk,
never cached across invocations, so the two tools never see a stale copy
of each other's writes.

ADR007V01 (superseding ADR003V01's own driver on this point): `folderlog`
is a deliberate, confirmed divergence from AdrPlus's own schema -- byte-
compatible round-tripping with the reference tool no longer holds for a
config carrying this field. It is also this schema's first field with a
computed default instead of being strictly required (see the `folderlog`
handling in `parse_repo_config`), so an `adr-config.adrplus` written
before this field existed keeps parsing unchanged.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from adrpy.core.casing import CASE_TRANSFORMS
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.io_retry import read_with_permission_retry
from adrpy.core.naming import parse_migration_pattern
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_marker_comment_syntax,
    reject_status_marker_forgery_characters,
)

VALID_SEPARATORS = ("-", "_", ".")
# Sourced from casing.py's own dispatch dict (the module that actually
# implements each transform) instead of a second, independently-typed
# tuple of the same 4 names.
VALID_CASE_TRANSFORMS = tuple(CASE_TRANSFORMS.keys())

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

# ADR005V01: the single source of truth for the 3 int fields' own bounds --
# `cli/config.py` and `cli/installconfig.py` used to each hand-write an
# identical copy of this dict; both now import it from here instead.
INT_FIELD_BOUNDS = {
    "lenseq": (LENSEQ_MIN, LENSEQ_MAX),
    "lenversion": (LENVERSION_MIN, LENVERSION_MAX),
    "lenrevision": (LENREVISION_MIN, LENREVISION_MAX),
}

# Every bound below comes from the same wizard, same reasoning as above.
# `prefix`'s charset restriction is also a real correctness requirement
# here, not just cosmetic: core/naming.py's filename parser assumes the
# prefix segment is letters-only to tell it apart from the digit run that
# follows.
PREFIX_MAX_LENGTH = 5
_PREFIX_PATTERN = re.compile(rf"^[A-Za-z]{{0,{PREFIX_MAX_LENGTH}}}$")

FOLDERADR_MAX_LENGTH = 50  # PromptEditFieldFolderRepo
# ADR007V01: no reference-tool wizard field to cite -- folderlog doesn't
# exist there. Same bound as folderadr's own for consistency, not fidelity.
FOLDERLOG_MAX_LENGTH = 50
# headerdisclaimer and status labels: wizard's own real values are 200 and
# 15 (PromptEditFieldHeaderText(headerdisclaimer, 200, ...); PromptEditFieldStatus's
# MaxLength(15)) -- user chose 100/25 instead, same as the lenseq-family bounds.
HEADER_DISCLAIMER_MAX_LENGTH = 100
HEADER_LABEL_MAX_LENGTH = 40  # PromptEditFieldHeaderText(<other header fields>, 40, ...)
STATUS_LABEL_MAX_LENGTH = 25
# Round 28: the reference tool's own wizard has no equivalent bound for
# this field at all (it's free-form body content, not a single prompt-
# edit-text field) -- a deliberate divergence, not a fidelity gap, added
# specifically so a bounded read of the config file itself (core/config.py's
# own read_config_text) can trust a fixed byte cap without risking a
# false rejection of a legitimate, if unusually long, template.
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

# ADR005V01: these 15 codes used to be built as f"config-{name}-too-long" at
# raise time -- each one still gets its own real FailureCodes attribute
# (a fixed, finite set), looked up here instead of formatted, so the
# registry stays the single source of truth for every code this module can
# actually raise.
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


def _validate_relative_repo_path_field(value, field_name, max_length, too_long_code, not_relative_code):
    """Shared by folderadr and folderlog (ADR007V01) -- both are a
    relative-path-to-a-repo-subfolder field with the exact same length
    and escape-path validation shape, differing only in their own max
    length and failure codes."""
    if len(value) > max_length:
        raise CommandError(too_long_code, f"{field_name} must be <= {max_length} characters.")
    if not _is_relative_path(value):
        raise CommandError(
            not_relative_code,
            f"{field_name} must be a relative path (a hostile config must never point outside the repository).",
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
    activeplugins: list
    disableplugins: bool


def load_repo_config(path):
    text = read_config_text(path)
    return parse_repo_config(text)


def default_repo_config_text():
    """The bundled, built-in default -- `init`'s own last-resort fallback
    (no --seed, no --language, no install-level config), and reused
    verbatim wherever else that same built-in default needs to be shown
    or seeded from, so there is exactly one place that reads this
    resource."""
    from importlib import resources

    resource = resources.files("adrpy.resources").joinpath("default_repo_config.json")
    return resource.read_text(encoding="utf-8")


# `language` doesn't just affect interactive UI text -- it also selects
# the DEFAULT header/status labels and the default template content a
# language-pack shortcut seeds. Shared by every command offering one
# (`init`, `installconfig`) instead of each keeping its own private copy.
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


# Round 28: this file is read on EVERY single command invocation
# (resolve_repo_and_target's own initial config load), plus init/
# installconfig --seed, with no size cap at all before this fix -- a
# 150MB config file measured a ~300MB peak-memory read. 64KB is
# generous relative to the schema's own worst case: every length-bounded
# field (including TEMPLATE_MAX_LENGTH, the one field this project added
# a bound to specifically to make this cap safe) summed at its own
# maximum, JSON-escaped, stays well under this. Deliberately NOT
# configurable -- a config-read cap can never be sourced from the
# config it is itself bounding (the value would have to be read first).
CONFIG_READ_MAX_BYTES = 65536
_CONFIG_READ_CHUNK_SIZE = 4096


def _read_config_bytes(path):
    """Reads at most `CONFIG_READ_MAX_BYTES` (plus at most one chunk's
    worth of overrun, used only to detect that the real file is larger,
    never returned) -- never the whole file regardless of its true size."""
    chunks = []
    total = 0
    with Path(path).open("rb") as handle:
        while total <= CONFIG_READ_MAX_BYTES:
            more = handle.read(_CONFIG_READ_CHUNK_SIZE)
            if not more:
                break
            chunks.append(more)
            total += len(more)
    return b"".join(chunks)


def read_config_text(path):
    """Shared by every reader of a config JSON file (the repo's own
    adr-config.adrplus, and init's --seed) -- invalid bytes must
    become a structured CommandError, not a raw UnicodeDecodeError with
    empty stdout. Bounded to CONFIG_READ_MAX_BYTES (see its own note) --
    raises config-file-too-large instead of reading further when the
    real file exceeds it.

    Retries a transient PermissionError the same way every other read in
    this codebase
    already does (core/lock.py's _read_lock, core/lifecycle.py's
    read_lines_with_report, cli/explore.py's _build_entry) -- this read
    goes through the identical atomic_write_text -> os.replace mechanism
    those retries exist to absorb, and it runs for every single command
    (resolve_repo_and_target's own initial config load), most of it
    BEFORE any lock or attach_warnings safety net is entered."""
    try:
        raw_bytes = read_with_permission_retry(lambda: _read_config_bytes(Path(path)))
        if len(raw_bytes) > CONFIG_READ_MAX_BYTES:
            raise CommandError(
                FailureCodes.CONFIG_FILE_TOO_LARGE,
                f"{path}: exceeds the {CONFIG_READ_MAX_BYTES}-byte config file size limit.",
            )
        # Path.read_text's own default (universal newlines) silently
        # translates CRLF/lone-CR to '\n' on read -- a plain bytes.decode
        # does not, which would otherwise change this function's own
        # observable output (confirmed live: broke a CRLF-fixture-comparing
        # test). Replicated explicitly so every caller (JSON parsing is
        # itself newline-agnostic, but read_install_config_text's own
        # pass-through contract is not) sees the exact same text as before.
        return raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as error:
        raise CommandError(FailureCodes.CONFIG_INVALID_ENCODING, f"{path}: {error}") from error


def parse_repo_config(text):
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError(FailureCodes.CONFIG_INVALID_JSON, str(error)) from error

    if not isinstance(raw, dict):
        raise CommandError(FailureCodes.CONFIG_INVALID_JSON, "Configuration root must be a JSON object.")

    lowered = {key.lower(): value for key, value in raw.items()}

    missing = [name for name in ALL_FIELDS if name != "folderlog" and name not in lowered]
    if missing:
        raise CommandError(FailureCodes.CONFIG_MISSING_FIELD, f"Missing required field(s): {', '.join(missing)}")

    extra = [key for key in raw if key.lower() not in ALL_FIELDS]
    if extra:
        raise CommandError(FailureCodes.CONFIG_UNEXPECTED_FIELD, f"Unexpected field(s): {', '.join(extra)}")

    # ADR007V01: folderlog defaults to today's exact computed sibling-of-
    # folderadr location when absent, so an adr-config.adrplus written
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

    for name in _BOOL_FIELDS:
        if not isinstance(lowered[name], bool):
            raise CommandError(FailureCodes.CONFIG_WRONG_TYPE, f"Field '{name}' must be a boolean.")

    for name in _LIST_FIELDS:
        value = lowered[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CommandError(FailureCodes.CONFIG_WRONG_TYPE, f"Field '{name}' must be an array of strings.")

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

    # ADR007V01: folderadr and folderlog are independently configurable and
    # each recursively scanned -- if either is the same directory as, or
    # nested inside, the other, each one's own scan would start seeing the
    # other's files (the same class of misrecognition hazard ADR004V02
    # already closed for --separator, applied here to a directory-
    # placement change instead of a naming-rule change). Compared by path
    # COMPONENT, not string prefix, so "doc/adr" vs "doc/adr2" never
    # false-matches.
    folderadr_parts = PurePosixPath(lowered["folderadr"]).parts
    folderlog_parts = PurePosixPath(lowered["folderlog"]).parts
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
            if error.code == FailureCodes.FIELD_IS_BLANK:
                raise CommandError(FailureCodes.CONFIG_FIELD_IS_BLANK, error.detail) from error
            raise CommandError(FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER, error.detail) from error

    # ADR004V01's hidden canonical marker (`<!-- Status -->` after the status
    # cell's parenthesized date) is only trustworthy if a status LABEL can
    # never itself contain the characters that mark a date/marker boundary --
    # otherwise a hostile statusnew/statusacc/statusrej/statussup forges a
    # marker and date the tool never wrote (confirmed live: a label of
    # "(20200101)<!--Rejected-->" made a decision created today read back as
    # Rejected/2020-01-01). Scoped to just these four fields, since no other
    # field is read by _parse_status_cell this way.
    for name in _STATUS_LABEL_FIELDS:
        try:
            reject_status_marker_forgery_characters(lowered[name], name)
        except CommandError as error:
            raise CommandError(FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER, error.detail) from error

    # parse_header's own is_migrated detection (core/header.py) is pure
    # substring matching for an HTML-comment-shaped tail on the row these
    # two fields build -- a hostile '<!--'/'-->' in either one forges
    # is_migrated=True on every ordinary file's header (confirmed live).
    for name in ("headertablefields", "headertablevalues"):
        try:
            reject_marker_comment_syntax(lowered[name], name)
        except CommandError as error:
            raise CommandError(FailureCodes.CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER, error.detail) from error

    # The reference tool validates a non-empty migrationpattern the same way,
    # rejecting anything that doesn't match the
    # N##:##T##[V##:##][R##:##][P##:##] shape.
    migrationpattern = lowered["migrationpattern"]
    if migrationpattern and parse_migration_pattern(migrationpattern) is None:
        raise CommandError(
            FailureCodes.CONFIG_MIGRATIONPATTERN_INVALID,
            "migrationpattern must match N##:##T##[V##:##][R##:##][P##:##], e.g. 'N00:04T04'.",
        )

    return RepoConfig(**{name: lowered[name] for name in ALL_FIELDS})
