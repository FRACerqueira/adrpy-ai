"""`init` command: initializes an ADR repository (harness Fase 7, item 1).

Ported from InitCommandHandler.cs. Plugin-baseline discovery/writing
(`WriteActivePluginsBaselineAsync` in the original) is intentionally not
implemented -- the plugin system is out of scope for now (confirmed
decision, to be recorded as a `deferred` decision-log entry once that log
exists): this command never touches `activeplugins` beyond what the
supplied or default config already contains.
"""

import os
from importlib import resources
from pathlib import Path

from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import resolve_within


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
                "name": "file",
                "type": "string",
                "required": False,
                "description": "Path to a config JSON to seed the repository with, instead of the built-in default.",
            },
        ],
    }


def run(args):
    path, file_arg = _parse_args(args)
    target = Path(path)

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {path}")

    config_path = target / "adr-config.adrplus"

    # Non-interactive by design (Fase 0: no wizard, no prompt to fall back
    # on) -- refuse cleanly instead of the original's confirm-or-refuse
    # prompt when no --file is given to bypass it.
    if config_path.exists() and file_arg is None:
        raise CommandError("config-already-exists", f"Configuration file already exists at: {config_path}")

    if file_arg is not None:
        file_path = Path(file_arg)
        if not file_path.is_file():
            raise CommandError("config-file-not-found", f"File not found: {file_arg}")
        config_text = file_path.read_text(encoding="utf-8")
    else:
        config_text = _default_config_text()

    config = parse_repo_config(config_text)

    max_number, max_version, max_revision = _max_existing_numbers(target, config)
    if len(str(max_number)) > config.lenseq:
        raise CommandError(
            "lenseq-too-small-for-existing-decisions",
            f"Existing decision number {max_number} does not fit in lenseq={config.lenseq}.",
        )
    if len(str(max_version)) > config.lenversion:
        raise CommandError(
            "lenversion-too-small-for-existing-decisions",
            f"Existing decision version {max_version} does not fit in lenversion={config.lenversion}.",
        )
    if config.lenrevision > 0 and len(str(max_revision)) > config.lenrevision:
        raise CommandError(
            "lenrevision-too-small-for-existing-decisions",
            f"Existing decision revision {max_revision} does not fit in lenrevision={config.lenrevision}.",
        )

    created = []
    # `os.linesep`: replicates the real terminator (host-OS-dependent, not
    # fixed -- see the Fase 2 commit) -- config_text is written verbatim,
    # exactly as the original does, never re-serialized from `config`.
    atomic_write_text(config_path, config_text, newline=os.linesep)
    created.append(str(config_path))

    # config.folderadr is already validated as relative (Fase 3), but a
    # "../.." traversal is still relative -- resolve_within is real path
    # resolution, the actual containment guard (Fase 5).
    folder_adr = resolve_within(target, config.folderadr)
    if not folder_adr.is_dir():
        folder_adr.mkdir(parents=True)
        created.append(str(folder_adr))

    return {"created": created}


def _parse_args(args):
    path = None
    file_arg = None
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--path":
            i += 1
            if i >= len(args):
                raise UsageError("--path requires a value")
            path = args[i]
        elif token == "--file":
            i += 1
            if i >= len(args):
                raise UsageError("--file requires a value")
            file_arg = args[i]
        else:
            raise UsageError(f"Unknown argument: {token}")
        i += 1
    if not path:
        raise UsageError("Missing required argument: --path")
    return path, file_arg


def _default_config_text():
    resource = resources.files("adrpy.resources").joinpath("default_repo_config.json")
    return resource.read_text(encoding="utf-8")


def _max_existing_numbers(target, config):
    """Recognizes both naming schemes (Fase 6 checklist) -- a legacy file's
    number must count too, or a shrunk lenseq could silently stop fitting
    it without this check ever noticing."""
    folder = resolve_within(target, config.folderadr)
    if not folder.is_dir():
        return 0, 0, 0

    max_number = max_version = max_revision = 0
    for candidate in folder.rglob("*.md"):
        found = parse_any_filename(candidate.name, config)
        if found is None:
            continue
        _, parsed = found
        max_number = max(max_number, parsed.number)
        max_version = max(max_version, parsed.version)
        max_revision = max(max_revision, parsed.revision or 0)
    return max_number, max_version, max_revision
