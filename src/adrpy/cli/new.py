"""`new` command: creates a new decision with status Proposed. `--open`
(would launch an external editor via an app-level setting) is permanently
not implemented --
a deliberate divergence, not a gap to fill later: adrpy-ai is
args-in/JSON-out for a non-interactive caller, with no session to hand
an opened editor back to (decision-log:
accepted-divergence--2026-09-15--cli--open-flag-not-implemented.md).
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.fs import cleanup_orphaned_temp_files, scan_tree
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.consistency import validate_repository
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.lifecycle import (
    find_by_unique_title,
    next_number,
    parse_refdate,
    resolve_target_and_config,
    validate_refdate_not_in_future,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, excluded_candidate_warning, orphan_cleanup_warning, retry_warning


def describe():
    return {
        "name": "new",
        "summary": "Creates a new decision, status Proposed.",
        "description": (
            "Creates a new decision with status Proposed. "
            "May fail with target-directory-not-found if --path does not point to an existing directory, "
            "or config-not-found if that directory has no adr-config.adrplus -- no write is attempted "
            "either way. "
            "Then, before any other rule, the whole repository is validated: if it breaks a consistency rule "
            "(the ones `adrpy check` reports -- a header that does not parse, a duplicate number, a supersede "
            "link that does not point both ways, a subdirectory that could not be scanned, ...), fails with "
            "repository-inconsistent, every broken rule listed in data.errors with a repair hint; no write "
            "is made. Fails with title-already-exists (data.existing_file names it) if "
            "another decision already has this title once case-transform normalized, or file-already-exists (data.file names it) "
            "if the resulting filename happens to already exist on disk -- neither write is made."
        ),
        "arguments": [
            {"name": "path", "alias": "-p", "type": "string", "required": True, "description": "Repository root directory."},
            {
                "name": "title",
                "alias": "-t",
                "type": "string",
                "required": True,
                "description": (
                    "Title of the new decision. Cannot contain '|' or a line-break-like character, or a "
                    "filesystem-unsafe character (`<>:\"/\\|?*` or a control character -- unlike every other "
                    "free-text field, title lands inside an actual filename component, not just a "
                    "header-table cell); also cannot consist entirely of whitespace/'_'/'-' (e.g. '-' or "
                    "'---') -- the case-transform step falls back to echoing such a value raw, which can "
                    "collide with the filename's own separator and produce a file the tool can never "
                    "recognize again (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "domain",
                "alias": "-d",
                "type": "string",
                "required": False,
                "description": (
                    "Optional domain header field. Cannot contain '|' or a line-break-like character "
                    "(field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    "Optional scope header field. Cannot contain '|' or a line-break-like character "
                    "(field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "refdate",
                "alias": "-r",
                "type": "string",
                "required": False,
                "description": (
                    "Reference date (YYYY-MM-DD); defaults to today. Must not be in the future -- a brand "
                    "new decision has no prior history to be before (refdate-invalid-format/"
                    "refdate-in-future)."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_NOT_FOUND: "--path's own directory has no adr-config.adrplus.",
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "title/domain/scope contains '|', a line-break-like character, or (title only) a filesystem-unsafe character; or title consists entirely of whitespace/'_'/'-'.",
                FailureCodes.FIELD_IS_BLANK: "domain or scope is non-empty but blank after stripping whitespace.",
                FailureCodes.REPOSITORY_INCONSISTENT: "The decisions folder breaks at least one consistency rule (the same ones `adrpy check` reports); data.errors lists every one, with its file and a repair hint. Nothing is written until the repository is repaired.",
                FailureCodes.TITLE_ALREADY_EXISTS: "Another decision already has this title, once both are normalized by the configured case transform.",
                FailureCodes.FILE_ALREADY_EXISTS: "The resulting filename already exists on disk.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The title, once case-transformed, would produce a filename this tool could never recognize again.",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
                FailureCodes.IO_ERROR: "The write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
            },
            CONFIG_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(
        args,
        required=("path", "title"),
        optional=("domain", "scope", "refdate"),
        aliases={"p": "path", "t": "title", "d": "domain", "s": "scope", "r": "refdate"},
    )
    title = flags["title"]
    domain = flags.get("domain", "")
    scope = flags.get("scope", "")

    target, _config_path, config = resolve_target_and_config(flags["path"])

    folder = resolve_within(target, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        # One walk of the folder feeds the orphan sweep and the validator.
        scan = scan_tree(folder) if folder.is_dir() else None
        if scan is not None:
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings, scan=scan))
            if warning:
                warnings.append(warning)
        # Before any other rule: title-uniqueness and next-number
        # allocation below read this one validated snapshot.
        snapshot = validate_repository(folder, config, scan=scan)
        warning = excluded_candidate_warning(list(snapshot.excluded))
        if warning:
            warnings.append(warning)

        reject_embedded_delimiter(title, "title")
        reject_filesystem_unsafe_title(title, "title")
        reject_title_with_no_case_transform_content(title, "title")
        reject_embedded_delimiter(domain, "domain")
        reject_embedded_delimiter(scope, "scope")

        refdate = parse_refdate(flags.get("refdate"))
        validate_refdate_not_in_future(refdate)

        decisions = [(decision.scheme, decision.name, decision.path) for decision in snapshot.decisions]

        existing = find_by_unique_title(title, config, decisions)
        if existing is not None:
            raise CommandError(
                FailureCodes.TITLE_ALREADY_EXISTS,
                f"A decision with this title already exists: {existing.name}",
                data={"existing_file": existing.name},
                warnings=warnings,
            )

        record = DecisionRecord(
            number=next_number(decisions),
            title=title,
            version=1,
            revision=1 if config.lenrevision > 0 else None,
            scope=scope,
            domain=domain,
            status_create="Proposed",
            date_create=refdate,
        )

        filename = build_filename(config, record)
        file_path = resolve_within(folder, filename)

        content = build_header(config, record) + config.template
        try:
            attempts = atomic_write_text(file_path, content, exclusive=True)
        except FileExistsError as error:
            raise CommandError(
                FailureCodes.FILE_ALREADY_EXISTS,
                f"File already exists: {filename}",
                data={"file": filename},
                warnings=warnings,
            ) from error
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # The canonical keyword, not the repo's configured label -- `explore`
    # reports status_create the same way for the same file, and the two
    # must agree even when statusnew is customized.
    return {"created": str(file_path), "status": "Proposed", "warnings": warnings}
