"""`init` command: initializes an ADR repository (harness Fase 7, item 1).

Ported from InitCommandHandler.cs. Plugin-baseline discovery/writing
(`WriteActivePluginsBaselineAsync` in the original) is intentionally not
implemented -- the plugin system is out of scope for now (confirmed
decision, to be recorded as a `deferred` decision-log entry once that log
exists): this command never touches `activeplugins` beyond what the
supplied or default config already contains.
"""

import json
from importlib import resources
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import parse_repo_config, read_config_text
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import is_within, resolve_within
from adrpy.core.warnings import retry_warning

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
        "description": "Initializes an ADR repository: writes adr-config.adrplus and creates the ADR folder.",
        "arguments": [
            {
                "name": "path",
                "type": "string",
                "required": True,
                "description": "Target repository root directory (must already exist).",
            },
            {
                "name": "seed",
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
                    "adr-config.adrplus outright -- config-already-exists is not raised when --seed is given."
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

    # Non-interactive by design (Fase 0: no wizard, no prompt to fall back
    # on) -- refuse cleanly instead of the original's confirm-or-refuse
    # prompt when no --seed is given to bypass it.
    if config_path.exists() and seed_arg is None:
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

    max_number, max_version, max_revision = _max_existing_numbers(target, config)
    if len(str(max_number)) > config.lenseq:
        raise CommandError(
            "lenseq-too-small-for-existing-decisions",
            f"Existing decision number {max_number} does not fit in lenseq={config.lenseq}.",
            data={"max_number": max_number, "lenseq": config.lenseq},
        )
    if len(str(max_version)) > config.lenversion:
        raise CommandError(
            "lenversion-too-small-for-existing-decisions",
            f"Existing decision version {max_version} does not fit in lenversion={config.lenversion}.",
            data={"max_version": max_version, "lenversion": config.lenversion},
        )
    if config.lenrevision > 0 and len(str(max_revision)) > config.lenrevision:
        raise CommandError(
            "lenrevision-too-small-for-existing-decisions",
            f"Existing decision revision {max_revision} does not fit in lenrevision={config.lenrevision}.",
            data={"max_revision": max_revision, "lenrevision": config.lenrevision},
        )

    created = []
    warnings = []
    # atomic_write_text normalizes to this host's line separator (Fase 2:
    # the real terminator is host-OS-dependent, not fixed) -- config_text
    # is otherwise written verbatim, never re-serialized from `config`.
    attempts = atomic_write_text(config_path, config_text)
    warning = retry_warning(attempts)
    if warning:
        warnings.append(warning)
    created.append(str(config_path))

    # config.folderadr is already validated as relative (Fase 3), but a
    # "../.." traversal is still relative -- resolve_within is real path
    # resolution, the actual containment guard (Fase 5).
    folder_adr = resolve_within(target, config.folderadr)
    if not folder_adr.is_dir():
        folder_adr.mkdir(parents=True)
        created.append(str(folder_adr))

    return {"created": created, "warnings": warnings}


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


def _max_existing_numbers(target, config):
    """Recognizes both naming schemes (Fase 6 checklist) -- a legacy file's
    number must count too, or a shrunk lenseq could silently stop fitting
    it without this check ever noticing."""
    folder = resolve_within(target, config.folderadr)
    if not folder.is_dir():
        return 0, 0, 0

    max_number = max_version = max_revision = 0
    for candidate in folder.rglob("*.md"):
        if not is_within(folder, candidate):
            continue
        found = parse_any_filename(candidate.name, config)
        if found is None:
            continue
        _, parsed = found
        max_number = max(max_number, parsed.number)
        max_version = max(max_version, parsed.version)
        max_revision = max(max_revision, parsed.revision or 0)
    return max_number, max_version, max_revision
