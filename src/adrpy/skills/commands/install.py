"""`install` command: writes the requested (provider, skill) pairs into a
target repository or the user's global config, protected by the
content-hash drift marker -- see ADR009V01."""

from adrpy.core.args import parse_flags
from adrpy.skills import installer
from adrpy.skills.providers import PROVIDERS
from adrpy.skills.resources import SKILL_NAMES


def describe():
    return {
        "name": "install",
        "summary": "Installs one or more bundled skills for one or more AI-coding-agent providers.",
        "description": (
            "Writes each requested (provider, skill) pair in the shape that provider expects: the full skill "
            "body for claude/cursor, a short stub pointing at one shared doc for copilot/agentsmd (for "
            "agentsmd, only that skill's own marked block in AGENTS.md). A file or block that is foreign (no "
            "marker), drifted (edited since it was generated) or malformed is left untouched unless --force "
            "is given, and a stub is never written while its shared doc is blocked (see "
            "doc/skills/README.md). --target global works with the claude provider only."
        ),
        "arguments": [
            {
                "name": "provider",
                "alias": "-p",
                "type": "string",
                "required": False,
                "description": (
                    "Comma-separated list of providers to install for: claude, cursor, copilot, "
                    "agentsmd. Defaults to 'all' (every bundled provider) when omitted -- or, with --target "
                    "global, to every provider that has a global scope (claude)."
                ),
            },
            {
                "name": "skill",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    f"Comma-separated list of skills to install: {', '.join(SKILL_NAMES)}. "
                    "Defaults to 'all' (every bundled skill) when omitted."
                ),
            },
            {
                "name": "target",
                "alias": "-t",
                "type": "string",
                "required": False,
                "description": (
                    "'project' (default) writes under --path; 'global' writes under the user's "
                    "own home directory (only meaningful for claude -- every other provider fails "
                    "with usage-error under --target global)."
                ),
            },
            {
                "name": "path",
                "type": "string",
                "required": False,
                "description": "Repository root to install into. Defaults to '.'. Only meaningful for --target project.",
            },
            {
                "name": "force",
                "alias": "-f",
                "type": "switch",
                "required": False,
                "description": (
                    "Overwrites a 'foreign', 'drifted', or (agentsmd) 'malformed' file/block instead of skipping it. "
                    "Presence-only: pass just '--force', not '--force true/false'."
                ),
            },
            {
                "name": "allow-external-links",
                "type": "switch",
                "required": False,
                "description": (
                    "Allows a file this call writes or removes to resolve, through a junction or symlink, "
                    "outside the target (--path, or the home directory for --target global) -- e.g. a "
                    "dotfiles setup linking .claude/skills elsewhere. Without it, such a call fails with "
                    "path-outside-repository before touching anything. Presence-only."
                ),
            },
        ],
        "failure_codes": [
            {"code": "target-directory-not-found", "condition": "--path does not point to an existing directory (never created) -- nothing was written."},
            {"code": "path-outside-repository", "condition": "A file this call would write or remove resolves, through a junction or symlink, outside the target (data.file/data.resolved name it) and --allow-external-links was not given -- nothing was written or removed."},
            {
                "code": "usage-error",
                "condition": (
                    "An unknown --provider, --skill, or --target value was given (--target accepts only "
                    "'project'/'global'), or --target global was combined with a provider that has no "
                    "global-scope concept (anything but claude)."
                ),
            },
            {
                "code": "io-error",
                "condition": (
                    "A read, write or delete failed (permission denied, full disk, a file over the 10MB read "
                    "limit, or a file that is not valid UTF-8 -- the detail names it). "
                    "data.installed/data.skipped list what this same call had already written before the failure, and warnings carries the warnings already collected -- the same shapes as the success result, as far as the call got."
                ),
            },
            {
                "code": "interrupted",
                "condition": "Interrupted (Ctrl+C) partway through; data.installed/data.skipped and warnings report what was already done, as for io-error.",
            },
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        optional=("provider", "target", "path", "skill"),
        switches=("force", "allow-external-links"),
        aliases={"p": "provider", "t": "target", "s": "skill", "f": "force"},
    )
    skills = _split(flags.get("skill"))
    scope = flags.get("target", "project").strip()
    # Omitted --provider with --target global means "every provider that
    # has a global scope", not "every provider" (which would always fail).
    if "provider" not in flags and scope == "global":
        providers = [provider for provider, spec in PROVIDERS.items() if spec["global_path"] is not None]
    else:
        providers = _split(flags.get("provider"))
    return installer.install(
        target_dir=flags.get("path", "."),
        providers=providers,
        skills=skills,
        scope=scope,
        force=flags.get("force", False),
        allow_external_links=flags.get("allow-external-links", False),
    )


def _split(value):
    if value is None:
        return ["all"]
    return [v.strip() for v in value.split(",") if v.strip()]
