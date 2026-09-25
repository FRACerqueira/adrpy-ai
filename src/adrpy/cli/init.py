"""`init` command: initializes an ADR repository.

Plugin-baseline discovery/writing is intentionally not implemented -- the
plugin system is out of scope for now (decision-log:
deferred--2026-09-15--plugins--sync-and-plugins-out-of-scope.md): this
command never touches `activeplugins` beyond what the supplied or
default config already contains (confirmed true even with --language's
own merge, since no language pack defines that field).
"""

from dataclasses import asdict
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import (
    SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES,
    SUPPORTED_LANGUAGES,
    default_repo_config_text,
    default_repo_config_text_for_language,
    load_repo_config,
    parse_repo_config,
    raise_config_file_empty,
    read_config_text,
    serialize_repo_config,
)
from adrpy.core.consistency import decision_names
from adrpy.core.errors import CommandError, FailureCodes, UsageError, build_failure_codes
from adrpy.core.fs import cleanup_orphaned_temp_files_for, scan_tree
from adrpy.core.install_config import read_install_config_text
from adrpy.core.lifecycle import resolve_target_and_config, validate_config_change
from adrpy.core.security import reject_aliased_repo_folders, resolve_within
from adrpy.core.warnings import (
    attach_warnings,
    excluded_candidate_warning,
    no_install_level_config_warning,
    orphan_cleanup_warning,
    retry_warning,
)


def describe():
    return {
        "name": "init",
        "summary": "Initializes an ADR repository: writes adr-config.adrplus and creates the decisions folder.",
        "description": (
            "Initializes an ADR repository: writes adr-config.adrplus and creates the decisions folder, "
            "refusing to replace an existing config unless --seed is given. With no --seed and no --language,"
            " seeds from this machine's install-level config (see installconfig) or, when there is none, from"
            " the built-in default, and then says so in `warnings`. A decisions folder that already exists is"
            " scanned first: every number already on disk must fit the configured "
            "lenseq/lenversion/lenrevision."
        ),
        "arguments": [
            {
                "name": "path",
                "alias": "-p",
                "type": "string",
                "required": True,
                "description": "Target repository root directory (must already exist).",
            },
            {
                "name": "seed",
                "alias": "-s",
                "type": "string",
                "required": False,
                # Named `seed`, not `file` -- every other command's
                # `--file` means "the decision file to mutate"; this alone
                # meant "a config JSON to seed the repo with", a naming
                # collision an agent generalizing across commands could
                # reasonably get wrong (decision-log: accepted-
                # divergence--2026-09-15--init--file-flag-renamed-to-seed.md).
                "description": (
                    "Path to a config JSON to seed the repository with, instead of the install-level "
                    "config (see the installconfig command) or the built-in default. Fails with "
                    "config-file-not-found if this path itself does not point to an existing file. "
                    "Unlike a bare `init` on a fresh path, this OVERWRITES an already-existing "
                    "adr-config.adrplus outright -- config-already-exists is not raised for a config that was "
                    "already there when --seed is given. The "
                    "existing file must still parse (its folderadr scopes the change "
                    "guards): a corrupted one fails with its own config-* code -- repair or remove it first. "
                    "If the seed's own folderadr differs from the current one AND the OLD folder already has "
                    "recognized decisions, fails with folderadr-change-blocked-by-existing-decisions instead "
                    "of silently orphaning them (same rule as the `config` command's own --folderadr guard); "
                    "if that check itself can't be completed (a subdirectory couldn't be scanned), fails "
                    "closed instead with folderadr-change-scan-incomplete rather than assuming nothing was "
                    "there. The NEW folder is checked too (same rule as `config`'s own guard): if it already "
                    "exists and holds a file that would newly parse as a decision under the resulting config, "
                    "fails with folderadr-change-would-adopt-unrelated-files (data.adopted_files lists the "
                    "file paths) instead of silently absorbing it and corrupting next-number allocation -- "
                    "the same scan-incomplete code above covers an unreadable subdirectory under the new "
                    "folder too; skipped entirely when the new folder does not exist yet. The seed's own "
                    "folderlog (ADR007V01) gets the same treatment: folderlog-change-blocked-by-existing-"
                    "entries / folderlog-change-would-adopt-unrelated-files / log-scan-incomplete, same rule "
                    "as the `config` command's own --folderlog guard. Likewise, if the "
                    "seed's own statusnew/statusacc/statusrej/statussup/separator/prefix/"
                    "migrationpattern differ from the current ones in a way that would break recognition of "
                    "an existing decision, fails with status-or-separator-change-blocked-by-existing-decisions "
                    "(ADR004V01/V02; same rule as the `config` command's own guard for these fields -- status "
                    "labels, --separator and --prefix block on any recognized decision (--separator's recognition "
                    "dependency is current-scheme-only, but a value already present in a legacy filename could "
                    "silently reclassify it under the current-scheme parser, so it cannot be scoped the way "
                    "--migrationpattern safely can); --migrationpattern blocks only if a LEGACY-scheme decision "
                    "that already has a header (migrated) exists. This is a PERMANENT block once the decisions it actually protects exist, with no "
                    "migration path -- for the four status fields, --separator and --prefix that means ANY recognized "
                    "decision, any scheme (the ADR004V01 marker future-proofs RECOGNITION of files that already "
                    "carry it against a later label change, but does not exempt THIS GUARD from refusing the "
                    "config change itself -- a marker-protected repository is blocked exactly the same as one "
                    "with none); for --migrationpattern it means a migrated LEGACY-scheme decision specifically. "
                    "data.changed_fields on this error names only the "
                    "field(s) actually blocking, not necessarily every field the seed touched) -- or "
                    "status-or-separator-change-scan-incomplete if that check itself can't be completed (that "
                    "sibling error's own data.changed_fields DOES list every guarded field touched, since it "
                    "fails closed unconditionally). If the seed's own separator (or prefix) would make a file NOT currently "
                    "recognized as a decision (by either scheme) newly parse as one, fails instead with "
                    "separator-change-would-adopt-unrelated-files (prefix-change-would-adopt-unrelated-files for the prefix; "
                    "data.adopted_files lists the file paths) -- "
                    "unlike migrationpattern, which is deliberately allowed to newly recognize pre-existing "
                    "legacy files as its own documented purpose, separator has no intentional-adoption use "
                    "case, so any file it would newly sweep in is treated as an unintended side effect and "
                    "blocked. This check only ever runs once the blocked-by-existing-decisions check above has "
                    "already passed, so it only ever fires when zero existing decisions are at risk -- those "
                    "two outcomes are mutually exclusive by construction, never coexisting. This guard's own scan-incomplete check runs BEFORE this command's own "
                    "init-existing-numbers-scan-incomplete check below, so when both an unreadable "
                    "subdirectory and a guarded field change occur together, status-or-separator-change-scan-"
                    "incomplete is what's raised (unless the seed also changes folderadr, whose own "
                    "folderadr-change-scan-incomplete fires first). See this command's own top-level description for "
                    "init-existing-numbers-scan-incomplete, which is NOT scoped to this --seed path either."
                ),
            },
            {
                "name": "language",
                "type": "string",
                "required": False,
                "description": (
                    f"Built-in default language pack for header/status labels and the default template "
                    f"(one of {SUPPORTED_LANGUAGES}); cannot be combined with --seed, and cannot be used "
                    "when an install-level config exists on this machine (both --seed and the "
                    "install-level config are full content sources; the caller must pick one explicitly "
                    "rather than have one silently win) -- fails with usage-error either way. Defaults to "
                    "en-us when neither --seed nor an install-level config apply."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_ALREADY_EXISTS: "adr-config.adrplus already exists and no --seed was given, or it appeared while init was running.",
                FailureCodes.CONFIG_FILE_NOT_FOUND: "--seed does not point to an existing file.",
                FailureCodes.LANGUAGE_NOT_SUPPORTED: "--language is not one of SUPPORTED_LANGUAGES.",
                FailureCodes.FOLDERADR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS: "--seed's own folderadr differs from the current one, and the OLD folder already has recognized decisions.",
                FailureCodes.FOLDERADR_CHANGE_SCAN_INCOMPLETE: "A subdirectory under the OLD or NEW folderadr could not be scanned while checking --seed's own folderadr change.",
                FailureCodes.FOLDERADR_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "The NEW folderadr already holds a file that would newly parse as a decision.",
                FailureCodes.FOLDERADR_FOLDERLOG_ALIAS_SAME_DIRECTORY: "folderadr and folderlog resolve to the same real directory (or one nested inside the other), typically via a symlink or junction.",
                FailureCodes.FOLDERLOG_CHANGE_BLOCKED_BY_EXISTING_ENTRIES: "--seed's own folderlog differs from the current one, and the OLD directory already has decision-log entries.",
                FailureCodes.FOLDERLOG_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "The NEW folderlog already holds a file that would newly parse as a decision-log entry.",
                FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE: "The OLD or NEW folderlog contains a .md file that does not parse as a valid decision-log entry.",
                FailureCodes.LOG_SCAN_INCOMPLETE: "A subdirectory under the OLD or NEW folderlog could not be scanned while checking --seed's own folderlog change.",
                FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS: "--seed's own status-label/separator/prefix/migrationpattern would break recognition of an existing decision.",
                FailureCodes.STATUS_OR_SEPARATOR_CHANGE_SCAN_INCOMPLETE: "A subdirectory under the OLD folderadr could not be scanned while checking a guarded field change.",
                FailureCodes.SEPARATOR_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "--seed's own separator would make a file NOT currently recognized as a decision newly parse as one.",
                FailureCodes.PREFIX_CHANGE_WOULD_ADOPT_UNRELATED_FILES: "--seed's own prefix would make a file NOT currently recognized as a decision newly parse as one (data.adopted_files).",
                FailureCodes.INIT_EXISTING_NUMBERS_SCAN_INCOMPLETE: "A subdirectory under the decisions folder could not be scanned while computing the existing max number/version/revision.",
                FailureCodes.LENSEQ_TOO_SMALL_FOR_EXISTING_DECISIONS: "The resulting lenseq is too narrow for a decision number that already exists on disk.",
                FailureCodes.LENVERSION_TOO_SMALL_FOR_EXISTING_DECISIONS: "The resulting lenversion is too narrow for a decision version that already exists on disk.",
                FailureCodes.LENREVISION_TOO_SMALL_FOR_EXISTING_DECISIONS: "The resulting lenrevision is too narrow for a decision revision that already exists on disk.",
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
        required=("path",),
        optional=("seed", "language"),
        aliases={"p": "path", "s": "seed"},
    )
    path = flags["path"]
    seed_arg = flags.get("seed")
    language_arg = flags.get("language")

    if seed_arg is not None and language_arg is not None:
        raise UsageError("--language cannot be combined with --seed.")

    target, config_path, _ = resolve_target_and_config(path, require_config=False)
    # Captured before any write below -- this is what decides whether the
    # write path below overwrites an existing config (and runs the change
    # guards against it) or is a genuine fresh bootstrap.
    config_already_existed = config_path.exists()

    # Non-interactive by design (no wizard, no prompt to fall back on) --
    # refuse cleanly when no --seed is given to replace the config.
    if config_already_existed and seed_arg is None:
        if read_config_text(config_path) == "":
            raise_config_file_empty(config_path)
        raise CommandError(FailureCodes.CONFIG_ALREADY_EXISTS, f"Configuration file already exists at: {config_path}")

    # ADR002V01: an install-level config, when present, is an implicit
    # seed -- the same reason --seed and --language are already mutually
    # exclusive above applies here too (both are full content sources;
    # the caller must pick one explicitly rather than have one silently
    # win). Deliberately read here, not earlier: this is real file I/O
    # plus schema validation against a file the caller never named, and on
    # every path above this point it's either unreachable (seed_arg given,
    # forces None below regardless) or would have already raised for an
    # unrelated reason -- a corrupted install-level config must never mask
    # target-directory-not-found or config-already-exists with an
    # unrelated schema error.
    install_config_text = None if seed_arg is not None else read_install_config_text()

    if language_arg is not None and install_config_text is not None:
        raise UsageError(
            "--language cannot be used when an install-level config exists on this machine "
            "(see the installconfig command); use --seed explicitly instead if you want to override it."
        )

    used_built_in_default_uninformed = False
    if seed_arg is not None:
        seed_path = Path(seed_arg)
        if not seed_path.is_file():
            raise CommandError(FailureCodes.CONFIG_FILE_NOT_FOUND, f"File not found: {seed_arg}")
        config_text = read_config_text(seed_path)
    elif language_arg is not None:
        config_text = default_repo_config_text_for_language(language_arg)
    elif install_config_text is not None:
        config_text = install_config_text
    else:
        config_text = default_repo_config_text()
        used_built_in_default_uninformed = True

    config = parse_repo_config(config_text)
    warnings = []
    if used_built_in_default_uninformed:
        warnings.append(no_install_level_config_warning())
    # A write of the config interrupted earlier leaves its temp at the
    # repository root, outside every folder sweep.
    with attach_warnings(warnings):
        warning = orphan_cleanup_warning(cleanup_orphaned_temp_files_for([config_path], warnings=warnings))
    if warning:
        warnings.append(warning)

    if config_already_existed:
        # --seed overwriting an ALREADY-existing repository: the PRE-edit
        # config scopes the change guards in _validate_and_write.
        old_config = load_repo_config(config_path)
        with attach_warnings(warnings):
            created = _validate_and_write(
                target, config_path, config_text, config, warnings, old_config=old_config
            )
        return {"created": created, "warnings": warnings}

    created = _validate_and_write(target, config_path, config_text, config, warnings)
    return {"created": created, "warnings": warnings}


def _validate_and_write(target, config_path, config_text, config, warnings, old_config=None):
    if old_config is not None:
        # --seed replacing an ALREADY-existing repository's config is
        # exactly as capable of orphaning or unrecognizing existing
        # decisions and decision-log entries as `config` is -- the same
        # guard, over the pre-edit folder and config. `old_config` is None
        # on the genuinely-fresh-bootstrap path (nothing existing to
        # orphan there). init is exempt from repository validation.
        old_folder = resolve_within(target, old_config.folderadr)
        validate_config_change(old_config, config, old_folder, target=target, warnings=warnings)

    # Same as explore/migrate and the repository scan -- an excluded
    # candidate is reported, not dropped with zero signal, since these are
    # the very numbers these three checks are about to gate a fresh init on.
    max_number, max_version, max_revision = _max_existing_numbers(target, config, warnings=warnings)
    if len(str(max_number)) > config.lenseq:
        raise CommandError(
            FailureCodes.LENSEQ_TOO_SMALL_FOR_EXISTING_DECISIONS,
            f"Existing decision number {max_number} does not fit in lenseq={config.lenseq}.",
            data={"max_number": max_number, "lenseq": config.lenseq},
            warnings=warnings,
        )
    if len(str(max_version)) > config.lenversion:
        raise CommandError(
            FailureCodes.LENVERSION_TOO_SMALL_FOR_EXISTING_DECISIONS,
            f"Existing decision version {max_version} does not fit in lenversion={config.lenversion}.",
            data={"max_version": max_version, "lenversion": config.lenversion},
            warnings=warnings,
        )
    if config.lenrevision > 0 and len(str(max_revision)) > config.lenrevision:
        raise CommandError(
            FailureCodes.LENREVISION_TOO_SMALL_FOR_EXISTING_DECISIONS,
            f"Existing decision revision {max_revision} does not fit in lenrevision={config.lenrevision}.",
            data={"max_revision": max_revision, "lenrevision": config.lenrevision},
            warnings=warnings,
        )

    created = []

    # config.folderadr is already validated as relative, but a "../.."
    # traversal is still relative -- resolve_within is real path
    # resolution, the actual containment guard.
    folder_adr = resolve_within(target, config.folderadr)
    # check-then-create is a real TOCTOU -- a concurrent process creating
    # this same directory between the check and the mkdir() call would
    # otherwise raise a raw FileExistsError. Unlike the config itself
    # (created exclusively below, refused if it appeared meanwhile), both
    # processes here want the exact same end state, so there's no
    # conflicting content to lose -- exist_ok=True closes it outright.
    #
    # Creating the folder here, ahead of the config commit below, means a
    # failure creating it aborts cleanly with nothing yet written, instead
    # of leaving config committed to a folderadr whose directory doesn't
    # exist, with every subsequent command failing with a generic
    # io-error until someone noticed.
    folder_already_existed = folder_adr.is_dir()
    folder_adr.mkdir(parents=True, exist_ok=True)

    # ADR007V01: same escape-path validation as folderadr above -- fails
    # fast on a hostile/malformed folderlog at init time, rather than
    # deferring to the first `adrpy log` call. Unlike folderadr, never
    # eagerly created here -- `adrpy log` already creates it lazily on
    # first write, and nothing else needs it to exist before then.
    resolve_within(target, config.folderlog)
    # Catches a junction/symlink planted inside the repo tree
    # BEFORE init ever runs, making folderadr and folderlog alias the
    # same real directory despite configured strings sharing no path
    # component -- the schema-time guard in core/config.py can never see
    # this (it never touches the filesystem). This is the first point
    # either folder's real, resolved location is knowable.
    reject_aliased_repo_folders(target, config)

    # Written in the one form `config` rewrites it in
    # (serialize_repo_config), whatever the source's own formatting, so a
    # later change is a diff of its own lines only. A fresh bootstrap
    # creates the config exclusively: one that appeared since the check
    # above is refused, not overwritten. --seed over an existing config is
    # an intended overwrite.
    try:
        attempts = atomic_write_text(config_path, serialize_repo_config(asdict(config)), exclusive=old_config is None)
    except FileExistsError as error:
        raise CommandError(
            FailureCodes.CONFIG_ALREADY_EXISTS,
            f"Configuration file already exists at: {config_path}",
            warnings=warnings,
        ) from error
    warning = retry_warning(attempts)
    if warning:
        warnings.append(warning)
    # This list's own order (config, then folder) does not follow the
    # filesystem operations above, which create the folder first.
    created.append(str(config_path))
    if not folder_already_existed:
        created.append(str(folder_adr))

    return created


def _max_existing_numbers(target, config, warnings=None):
    """Recognizes both naming schemes -- a legacy file's number must count
    too, or a shrunk lenseq could silently stop fitting it without this
    check ever noticing -- through core/consistency.decision_names, so a
    file the phase rule says is not a decision does not count.

    `warnings`, when given, reports any candidate excluded for escaping
    the folder -- same convention as explore/migrate."""
    folder = resolve_within(target, config.folderadr)
    if not folder.is_dir():
        return 0, 0, 0

    max_number = max_version = max_revision = 0
    scan = scan_tree(folder)
    excluded = list(scan.excluded)
    names, _unheadered = decision_names(scan, config)
    for parsed in (name.parsed for name in names):
        max_number = max(max_number, parsed.number)
        max_version = max(max_version, parsed.version)
        max_revision = max(max_revision, parsed.revision or 0)
    # Fails closed on a subdirectory the scan could not list, instead of
    # warning -- this feeds a real safety decision (lenseq/lenversion/
    # lenrevision must fit every EXISTING number), so an under-reported
    # max must never be silently trusted the way explore's own
    # best-effort listing can.
    unreadable = list(scan.unreadable)
    if unreadable:
        raise CommandError(
            FailureCodes.INIT_EXISTING_NUMBERS_SCAN_INCOMPLETE,
            f"Cannot safely determine existing decision numbers: {len(unreadable)} subdirectory/"
            "subdirectories could not be scanned (permission denied or similar).",
            data={"folder": str(folder), "unreadable": unreadable},
            warnings=warnings,
        )
    if warnings is not None:
        warning = excluded_candidate_warning(excluded)
        if warning:
            warnings.append(warning)
    return max_number, max_version, max_revision
