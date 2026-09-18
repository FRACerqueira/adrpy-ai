"""`init` command: initializes an ADR repository (harness Fase 7, item 1).

Ported from InitCommandHandler.cs. Plugin-baseline discovery/writing
(`WriteActivePluginsBaselineAsync` in the original) is intentionally not
implemented -- the plugin system is out of scope for now (decision-log:
deferred--2026-09-15--plugins--sync-and-plugins-out-of-scope.md): this
command never touches `activeplugins` beyond what the supplied or
default config already contains (confirmed true even with --language's
own merge, since no language pack defines that field).
"""

import json
from importlib import resources
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import load_repo_config, parse_repo_config, read_config_text
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.lifecycle import (
    reject_folderadr_change_if_decisions_exist,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import find_unreadable_subdirectories, is_within, resolve_within
from adrpy.core.warnings import attach_warnings, excluded_candidate_warning, retry_warning

# Matches adrplus.json's own documented `language` values verbatim.
# Confirmed against AdrPlusRepoConfig.cs's field initializers: `language`
# in the real tool doesn't just affect interactive UI text -- it also
# selects the DEFAULT header/status labels (from a per-culture .resx) and
# the default template content (a per-culture template file) baked into
# a newly init'd repo. Each pack below was extracted verbatim from
# AdrSource's own resources, never hand-translated.
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


def describe():
    return {
        "name": "init",
        "description": (
            "Initializes an ADR repository: writes adr-config.adrplus and creates the ADR folder. "
            "Not safe to call concurrently on a FRESH --path with no config yet (deliberately, see "
            "doc/adr/ADR001V01-...): two simultaneous first-time calls can silently overwrite one "
            "another's config, both reporting success -- callers must ensure at most one first-time "
            "init runs per fresh repository path at a time. --seed overwriting an ALREADY-existing "
            "repository's config is, by contrast, protected by the same repository lock every other "
            "write command uses (round 5 stability re-run, Finding 1). May fail with "
            "init-existing-numbers-scan-incomplete if a subdirectory under the decisions folder could not "
            "be scanned (permission denied or similar) -- the existing max number/version/revision, which "
            "lenseq/lenversion/lenrevision must fit, can't be trusted from an incomplete scan. Unlike "
            "every other failure documented on the --seed argument below, this one is NOT scoped to the "
            "already-existing-repository path -- it can also fire on a genuinely fresh `init` if a "
            "decisions folder with an unreadable subdirectory already exists under the target path."
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
                # Usability backlog item B2: named `seed`, not `file` --
                # every other command's `--file` means "the decision file
                # to mutate"; this alone meant "a config JSON to seed the
                # repo with", a naming collision an agent generalizing
                # across commands could reasonably get wrong. Deliberate
                # divergence from the real tool's own `-f/--file` naming,
                # confirmed with the user (decision-log: accepted-
                # divergence--2026-09-15--init--file-flag-renamed-to-seed.md).
                "description": (
                    "Path to a config JSON to seed the repository with, instead of the built-in default. "
                    "Unlike a bare `init` on a fresh path, this OVERWRITES an already-existing "
                    "adr-config.adrplus outright -- config-already-exists is not raised when --seed is given. "
                    "If the seed's own folderadr differs from the current one AND the OLD folder already has "
                    "recognized decisions, fails with folderadr-change-blocked-by-existing-decisions instead "
                    "of silently orphaning them (same rule as the `config` command's own --folderadr guard); "
                    "if that check itself can't be completed (a subdirectory couldn't be scanned), fails "
                    "closed instead with folderadr-change-scan-incomplete rather than assuming nothing was "
                    "there. On this same already-existing-repository path, may also fail with "
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
                    f"(one of {SUPPORTED_LANGUAGES}); cannot be combined with --seed. Defaults to en-us."
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
    target = Path(path)

    if seed_arg is not None and language_arg is not None:
        raise UsageError("--language cannot be combined with --seed.")

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {path}")

    config_path = target / "adr-config.adrplus"
    # Captured before any write below: round 5 stability re-run, Finding 1
    # -- this is what decides whether the write path below is live shared
    # state (needs a lock) or a genuine fresh bootstrap (nothing to race
    # against yet).
    config_already_existed = config_path.exists()

    # Non-interactive by design (Fase 0: no wizard, no prompt to fall back
    # on) -- refuse cleanly instead of the original's confirm-or-refuse
    # prompt when no --seed is given to bypass it.
    if config_already_existed and seed_arg is None:
        raise CommandError("config-already-exists", f"Configuration file already exists at: {config_path}")

    if seed_arg is not None:
        seed_path = Path(seed_arg)
        if not seed_path.is_file():
            raise CommandError("config-file-not-found", f"File not found: {seed_arg}")
        config_text = read_config_text(seed_path)
    elif language_arg is not None:
        config_text = _default_config_text_for_language(language_arg)
    else:
        config_text = _default_config_text()

    config = parse_repo_config(config_text)
    warnings = []

    if config_already_existed:
        # Round 5 stability re-run, Finding 1 (HIGH): --seed overwriting an
        # ALREADY-existing repository is live shared state, not bootstrap
        # -- ADR001's exemption for init only covers the truly-fresh-path
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
                # Round 6 stability re-run, Finding A-1: `bootstrap_config`
                # above is read BEFORE this lock, then was handed straight
                # to the folderadr-change guard unrefreshed -- if a
                # concurrent process already changed folderadr by the time
                # this lock was acquired, the guard scanned the wrong
                # (stale) folder, or even skipped scanning entirely when
                # the seed happened to carry that same stale value. Reads
                # fresh and aborts instead of trusting the pre-lock read.
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
        # Round 5 stability re-run, Finding 5 (confirmed with the user):
        # same class as config.py's own --folderadr guard -- --seed
        # changing folderadr on an already-existing repository is exactly
        # as capable of orphaning existing decisions as `config` is.
        # `old_config` is None on the genuinely-fresh-bootstrap path
        # (nothing existing to orphan there, and no "old" repo to compare
        # against).
        old_folder = resolve_within(target, old_config.folderadr)
        reject_folderadr_change_if_decisions_exist(
            old_folder, old_config.folderadr, config.folderadr, old_config, warnings=warnings
        )

    # Round 4 observability audit, Finding 3: same as scan_decisions/
    # explore/migrate -- an is_within-excluded candidate used to be
    # dropped with zero signal, even from the very numbers these three
    # checks are about to gate a fresh init on.
    max_number, max_version, max_revision = _max_existing_numbers(target, config, warnings=warnings)
    if len(str(max_number)) > config.lenseq:
        raise CommandError(
            "lenseq-too-small-for-existing-decisions",
            f"Existing decision number {max_number} does not fit in lenseq={config.lenseq}.",
            data={"max_number": max_number, "lenseq": config.lenseq},
            warnings=warnings,
        )
    if len(str(max_version)) > config.lenversion:
        raise CommandError(
            "lenversion-too-small-for-existing-decisions",
            f"Existing decision version {max_version} does not fit in lenversion={config.lenversion}.",
            data={"max_version": max_version, "lenversion": config.lenversion},
            warnings=warnings,
        )
    if config.lenrevision > 0 and len(str(max_revision)) > config.lenrevision:
        raise CommandError(
            "lenrevision-too-small-for-existing-decisions",
            f"Existing decision revision {max_revision} does not fit in lenrevision={config.lenrevision}.",
            data={"max_revision": max_revision, "lenrevision": config.lenrevision},
            warnings=warnings,
        )

    created = []

    # config.folderadr is already validated as relative (Fase 3), but a
    # "../.." traversal is still relative -- resolve_within is real path
    # resolution, the actual containment guard (Fase 5).
    folder_adr = resolve_within(target, config.folderadr)
    # Round 4 second corroboration pass: check-then-create was a real
    # TOCTOU -- a concurrent process creating this same directory between
    # the check and the mkdir() call raised a raw FileExistsError (a
    # clean io-error via __main__'s own OSError safety net, not a crash,
    # but a generic code for a benign race: unlike the config-already-
    # exists race this project already accepts as risk, both processes
    # here want the exact same end state, so there's no conflicting
    # content to lose -- exist_ok=True closes it outright rather than
    # just reporting it better.
    #
    # Round 7 resilience audit, Finding 3 (retraction of this function's
    # own previous mkdir-AFTER-write order): moved ahead of the config
    # commit below -- a failure creating this folder now aborts cleanly
    # with nothing yet written, instead of leaving config committed to a
    # folderadr whose directory doesn't exist, and every subsequent
    # command failing with a generic io-error until someone noticed.
    folder_already_existed = folder_adr.is_dir()
    folder_adr.mkdir(parents=True, exist_ok=True)

    if lock is not None:
        # ADR001, part 3: guarantees this write never commits blindly if
        # the lease was reclaimed.
        lock.verify_still_held()
    # atomic_write_text normalizes to this host's line separator (Fase 2:
    # the real terminator is host-OS-dependent, not fixed) -- config_text
    # is otherwise written verbatim, never re-serialized from `config`.
    attempts = atomic_write_text(config_path, config_text)
    warning = retry_warning(attempts)
    if warning:
        warnings.append(warning)
    # `created`'s own reported order (config, then folder) is unchanged
    # from before this fix -- only the underlying filesystem operations
    # above were reordered, not what callers see reported.
    created.append(str(config_path))
    if not folder_already_existed:
        created.append(str(folder_adr))

    return created


def _default_config_text():
    resource = resources.files("adrpy.resources").joinpath("default_repo_config.json")
    return resource.read_text(encoding="utf-8")


def _load_language_pack(language):
    if language not in SUPPORTED_LANGUAGES:
        raise CommandError(
            "init-language-not-supported",
            f"--language must be one of {SUPPORTED_LANGUAGES}, got: {language}",
        )
    resource = resources.files("adrpy.resources.language_packs").joinpath(f"{language}.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _default_config_text_for_language(language):
    """Merges a language pack's ~17 fields (labels/status/template) onto
    the built-in default -- everything else (folderadr, separator,
    lenseq/lenversion/lenrevision, casetransform, migrationpattern) is
    language-independent in the real tool too (AdrPlusRepoConfig.cs's own
    field initializers), so it keeps the same built-in default regardless
    of --language."""
    base = json.loads(_default_config_text())
    base.update(_load_language_pack(language))
    return json.dumps(base, indent=2, ensure_ascii=False)


def _max_existing_numbers(target, config, warnings=None):
    """Recognizes both naming schemes (Fase 6 checklist) -- a legacy file's
    number must count too, or a shrunk lenseq could silently stop fitting
    it without this check ever noticing.

    `warnings`, when given, reports (round 4 observability audit, Finding
    3) any candidate is_within excluded -- same convention as
    scan_decisions/explore/migrate."""
    folder = resolve_within(target, config.folderadr)
    if not folder.is_dir():
        return 0, 0, 0

    max_number = max_version = max_revision = 0
    excluded = []
    # Round 4 performance front: resolved once, not once per candidate --
    # see is_within's own note.
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
    # Round 6 resilience re-run, Finding B, class closure: rglob above
    # silently swallows an OSError from an unreadable subdirectory -- see
    # find_unreadable_subdirectories' own note.
    #
    # Round 8 stability audit, class closure: fails closed instead of
    # warning -- this feeds a real safety decision (lenseq/lenversion/
    # lenrevision must fit every EXISTING number), so an under-reported
    # max must never be silently trusted the way explore's own best-
    # effort listing can.
    unreadable = find_unreadable_subdirectories(folder)
    if unreadable:
        raise CommandError(
            "init-existing-numbers-scan-incomplete",
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
