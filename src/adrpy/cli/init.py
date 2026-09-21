"""`init` command: initializes an ADR repository.

Plugin-baseline discovery/writing is intentionally not implemented -- the
plugin system is out of scope for now (decision-log:
deferred--2026-09-15--plugins--sync-and-plugins-out-of-scope.md): this
command never touches `activeplugins` beyond what the supplied or
default config already contains (confirmed true even with --language's
own merge, since no language pack defines that field).
"""

from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import (
    SUPPORTED_LANGUAGES,
    default_repo_config_text,
    default_repo_config_text_for_language,
    load_repo_config,
    parse_repo_config,
    read_config_text,
)
from adrpy.core.errors import CommandError, FailureCodes, UsageError
from adrpy.core.install_config import read_install_config_text
from adrpy.core.lifecycle import (
    reject_folderadr_change_if_decisions_exist,
    reject_status_or_separator_change_if_decisions_exist,
    resolve_target_and_config,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import find_unreadable_subdirectories, is_within, resolve_within
from adrpy.core.warnings import attach_warnings, excluded_candidate_warning, no_install_level_config_warning, retry_warning


def describe():
    return {
        "name": "init",
        "summary": "Initializes an ADR repository: writes adr-config.adrplus and creates the decisions folder.",
        "description": (
            "Initializes an ADR repository: writes adr-config.adrplus and creates the ADR folder. "
            "May fail with target-directory-not-found if --path does not point to an existing directory "
            "-- no write is attempted. Fails with config-already-exists if adr-config.adrplus is already "
            "there and no --seed was given -- use `config` to edit an existing repository's settings "
            "instead, or pass --seed to overwrite it outright. "
            "With no --seed and no --language, seeds from the install-level config (see the "
            "installconfig command; ADR002V01) if one has been set up on this machine, or from the "
            "built-in default otherwise -- the install-level config not existing is the normal state "
            "for any installation that has never run installconfig, not an error; the result's own "
            "`warnings` names this and points at `installconfig` when it happens, since it is the one "
            "case where nothing informed this repository's own settings at all. "
            "Not safe to call concurrently on a FRESH --path with no config yet (deliberately, see "
            "doc/adr/ADR001V01-...): two simultaneous first-time calls can silently overwrite one "
            "another's config, both reporting success -- callers must ensure at most one first-time "
            "init runs per fresh repository path at a time. --seed overwriting an ALREADY-existing "
            "repository's config is, by contrast, protected by the same repository lock every other "
            "write command uses. May fail with "
            "init-existing-numbers-scan-incomplete if a subdirectory under the decisions folder could not "
            "be scanned (permission denied or similar) -- the existing max number/version/revision, which "
            "lenseq/lenversion/lenrevision must fit, can't be trusted from an incomplete scan. Unlike "
            "every other failure documented on the --seed argument below, this one is NOT scoped to the "
            "already-existing-repository path -- it can also fire on a genuinely fresh `init` if a "
            "decisions folder with an unreadable subdirectory already exists under the target path. "
            "Once that scan itself succeeds, may also fail with lenseq-too-small-for-existing-decisions/"
            "lenversion-too-small-for-existing-decisions/lenrevision-too-small-for-existing-decisions "
            "(each names the offending existing number and the configured length in `data`) if the "
            "resulting lenseq/lenversion/lenrevision is too narrow for a decision that already exists on "
            "disk -- same scoping as the scan-incomplete check above (can fire on a genuinely fresh "
            "`init` too, not just --seed on an existing repository)."
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
                # reasonably get wrong. Deliberate divergence from the real
                # tool's own `-f/--file` naming (decision-log: accepted-
                # divergence--2026-09-15--init--file-flag-renamed-to-seed.md).
                "description": (
                    "Path to a config JSON to seed the repository with, instead of the install-level "
                    "config (see the installconfig command) or the built-in default. Fails with "
                    "config-file-not-found if this path itself does not point to an existing file. "
                    "Unlike a bare `init` on a fresh path, this OVERWRITES an already-existing "
                    "adr-config.adrplus outright -- config-already-exists is not raised when --seed is given. "
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
                    "folder too; skipped entirely when the new folder does not exist yet. Likewise, if the "
                    "seed's own statusnew/statusacc/statusrej/statussup/separator/"
                    "migrationpattern differ from the current ones in a way that would break recognition of "
                    "an existing decision, fails with status-or-separator-change-blocked-by-existing-decisions "
                    "(ADR004V01/V02; same rule as the `config` command's own guard for these fields -- status "
                    "labels and --separator block on any recognized decision (--separator's recognition "
                    "dependency is current-scheme-only, but a value already present in a legacy filename could "
                    "silently reclassify it under the current-scheme parser, so it cannot be scoped the way "
                    "--migrationpattern safely can); --migrationpattern blocks only if a LEGACY-scheme decision "
                    "exists. This is a PERMANENT block once the decisions it actually protects exist, with no "
                    "migration path -- for the four status fields and --separator that means ANY recognized "
                    "decision, any scheme (the ADR004V01 marker future-proofs RECOGNITION of files that already "
                    "carry it against a later label change, but does not exempt THIS GUARD from refusing the "
                    "config change itself -- a marker-protected repository is blocked exactly the same as one "
                    "with none); for --migrationpattern it means a LEGACY-scheme decision specifically. "
                    "data.changed_fields on this error names only the "
                    "field(s) actually blocking, not necessarily every field the seed touched) -- or "
                    "status-or-separator-change-scan-incomplete if that check itself can't be completed (that "
                    "sibling error's own data.changed_fields DOES list every guarded field touched, since it "
                    "fails closed unconditionally). If the seed's own separator would make a file NOT currently "
                    "recognized as a decision (by either scheme) newly parse as one, fails instead with "
                    "separator-change-would-adopt-unrelated-files (data.adopted_files lists the file paths) -- "
                    "unlike migrationpattern, which is deliberately allowed to newly recognize pre-existing "
                    "legacy files as its own documented purpose, separator has no intentional-adoption use "
                    "case, so any file it would newly sweep in is treated as an unintended side effect and "
                    "blocked. This check only ever runs once the blocked-by-existing-decisions check above has "
                    "already passed, so it only ever fires when zero existing decisions are at risk -- those "
                    "two outcomes are mutually exclusive by construction, never coexisting. This guard's own scan-incomplete check runs BEFORE this command's own "
                    "init-existing-numbers-scan-incomplete check below, so when both an unreadable "
                    "subdirectory and a guarded field change occur together, status-or-separator-change-scan-"
                    "incomplete is what's raised. On this same already-existing-repository path, may also "
                    "fail with "
                    "repository-locked, lock-lost (see this command's own top-level description), or "
                    "folderadr-changed-after-lock-acquired (a concurrent config change moved folderadr while "
                    "this call was acquiring the lock -- retry) -- never on a genuinely fresh path, which "
                    "takes no lock at all. See this command's own top-level description for "
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
    # write path below is live shared state (needs a lock) or a genuine
    # fresh bootstrap (nothing to race against yet).
    config_already_existed = config_path.exists()

    # Non-interactive by design (no wizard, no prompt to fall back on) --
    # refuse cleanly instead of the reference tool's confirm-or-refuse prompt
    # when no --seed is given to bypass it.
    if config_already_existed and seed_arg is None:
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

    if config_already_existed:
        # --seed overwriting an ALREADY-existing repository is live shared
        # state, not bootstrap -- ADR001's exemption for init only covers
        # the truly-fresh-path
        # case, where the decisions folder doesn't exist yet to even
        # locate a lock in. Here it already does (every prior init created
        # it), so lock it exactly like config.py's own bootstrap-then-lock
        # pattern: read the PRE-edit config just to find where the lock
        # lives, then do the whole scan-validate-write under that lock,
        # freshly -- closing both the lost-update (a concurrent config
        # write silently clobbered) and the narrower lenseq/lenversion/
        # lenrevision gating race (scanned without a lock at all before).
        bootstrap_config = load_repo_config(config_path)
        lock_folder = resolve_within(target, bootstrap_config.folderadr)
        with attach_warnings(warnings):
            with acquire_repo_lock(lock_folder) as lock:
                warnings.extend(lock.warnings)
                # `bootstrap_config` above is read BEFORE this lock -- if a
                # concurrent process already changed folderadr by the time
                # this lock was acquired, handing it straight to the
                # folderadr-change guard unrefreshed would scan the wrong
                # (stale) folder, or skip scanning entirely when the seed
                # happened to carry that same stale value. Reads fresh and
                # aborts instead of trusting the pre-lock read.
                bootstrap_config = verify_folderadr_unchanged_since_lock(
                    config_path, bootstrap_config.folderadr, warnings=warnings
                )
                created = _validate_and_write(
                    target, config_path, config_text, config, warnings, lock, old_config=bootstrap_config
                )
        return {"created": created, "warnings": warnings}

    created = _validate_and_write(target, config_path, config_text, config, warnings, lock=None)
    return {"created": created, "warnings": warnings}


def _validate_and_write(target, config_path, config_text, config, warnings, lock, old_config=None):
    if old_config is not None:
        # Same class as config.py's own --folderadr guard -- --seed
        # changing folderadr on an already-existing repository is exactly
        # as capable of orphaning existing decisions as `config` is.
        # `old_config` is None on the genuinely-fresh-bootstrap path
        # (nothing existing to orphan there, and no "old" repo to compare
        # against).
        old_folder = resolve_within(target, old_config.folderadr)
        reject_folderadr_change_if_decisions_exist(
            old_folder,
            old_config.folderadr,
            config.folderadr,
            old_config,
            target=target,
            new_config=config,
            warnings=warnings,
        )
        # ADR004V01: --seed replacing an ALREADY-existing repository's
        # config is exactly as capable of breaking status-label/separator
        # recognition of existing decisions as `config` is -- same guard,
        # same pre-edit `old_folder`/`old_config`.
        reject_status_or_separator_change_if_decisions_exist(old_folder, old_config, config, warnings=warnings)

    # Same as scan_decisions/explore/migrate -- an is_within-excluded
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
    # otherwise raise a raw FileExistsError. Unlike the config-already-
    # exists race this project already accepts as risk, both processes
    # here want the exact same end state, so there's no conflicting
    # content to lose -- exist_ok=True closes it outright.
    #
    # Creating the folder here, ahead of the config commit below, means a
    # failure creating it aborts cleanly with nothing yet written, instead
    # of leaving config committed to a folderadr whose directory doesn't
    # exist, with every subsequent command failing with a generic
    # io-error until someone noticed.
    folder_already_existed = folder_adr.is_dir()
    folder_adr.mkdir(parents=True, exist_ok=True)

    if lock is not None:
        # ADR001, part 3: guarantees this write never commits blindly if
        # the lease was reclaimed.
        lock.verify_still_held()
    # atomic_write_text normalizes to this host's line separator (the real
    # terminator is host-OS-dependent, not fixed) -- config_text is
    # otherwise written verbatim, never re-serialized from `config`.
    attempts = atomic_write_text(config_path, config_text)
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
    check ever noticing.

    `warnings`, when given, reports any candidate is_within excluded --
    same convention as scan_decisions/explore/migrate."""
    folder = resolve_within(target, config.folderadr)
    if not folder.is_dir():
        return 0, 0, 0

    max_number = max_version = max_revision = 0
    excluded = []
    # Resolved once, not once per candidate -- see is_within's own note.
    try:
        resolved_folder = folder.resolve()
    except (OSError, ValueError):
        resolved_folder = None
    for candidate in folder.rglob("*.md"):
        if not is_within(folder, candidate, resolved_base=resolved_folder):
            excluded.append(candidate)
            continue
        found = parse_any_filename(candidate.name, config)
        if found is None:
            continue
        _, parsed = found
        max_number = max(max_number, parsed.number)
        max_version = max(max_version, parsed.version)
        max_revision = max(max_revision, parsed.revision or 0)
    # rglob above silently swallows an OSError from an unreadable
    # subdirectory -- see find_unreadable_subdirectories' own note.
    # Fails closed instead of warning -- this feeds a real safety decision
    # (lenseq/lenversion/lenrevision must fit every EXISTING number), so an
    # under-reported max must never be silently trusted the way explore's
    # own best-effort listing can.
    unreadable = find_unreadable_subdirectories(folder)
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
