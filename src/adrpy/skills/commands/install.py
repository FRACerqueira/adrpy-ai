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
            "Writes the requested (provider, skill) pairs to disk, wrapped in the shape each "
            "provider expects (full skill body for claude/cursor, a short stub pointing at one "
            "shared doc for copilot/agentsmd). Every write is protected by a content-hash marker: "
            "a file that already exists with no marker at all is reported as 'foreign' and left "
            "untouched; a file whose marker no longer matches its own current content is reported "
            "as 'drifted' and also left untouched -- in both cases only --force overwrites it. For "
            "agentsmd, a skill's own start/end block that's truncated (missing its closing tag) or "
            "duplicated (more than one complete block for the same skill), or that crosses another "
            "skill's block (nested or overlapping -- only reachable by hand-editing), is reported as "
            "'malformed' and given the same treatment as 'foreign'. Tags indented four spaces or more (or "
            "by a tab) count as that skill's block only when its marker hash still matches -- a block an "
            "editor re-indented, updated in place with its indentation kept; any other indented copy is "
            "treated as your own text, never touched, and a new block is appended with a warning saying "
            "why. A new shared doc is written only when some stub-mode provider in the call will be (an existing one is updated as before). "
            "For copilot/agentsmd, the one shared doc a skill's stub points at is written (and "
            "reported in `installed` under provider 'shared-doc') before that provider's own file, "
            "never after -- if the shared doc itself is 'foreign'/'drifted' and blocked (without "
            "--force), every stub-mode provider that would reference it is also skipped, reported "
            "with reason 'shared-doc-blocked', rather than writing a stub that points at content "
            "never actually verified or regenerated. --target global combined with any provider "
            "other than claude fails with usage-error (cursor/copilot/agentsmd have no global-scope "
            "concept). Never runs unless explicitly invoked -- adrpy-skills is a separate entry "
            "point from adrpy and is never called by it."
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
