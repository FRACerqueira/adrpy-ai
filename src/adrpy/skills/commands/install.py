"""`install` command: writes the requested (provider, skill) pairs into a
target repository or the user's global config, protected by the
content-hash drift marker -- see ADR009V01."""

from adrpy.core.args import parse_flags
from adrpy.skills import installer
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
            "as 'drifted' and also left untouched -- in both cases only --force overwrites it. "
            "--target global combined with any provider other than claude fails with usage-error "
            "(cursor/copilot/agentsmd have no global-scope concept). Never runs unless explicitly "
            "invoked -- adrpy-skills is a separate entry point from adrpy and is never called by it."
        ),
        "arguments": [
            {
                "name": "provider",
                "alias": "-p",
                "type": "string",
                "required": False,
                "description": (
                    "Comma-separated list of providers to install for: claude, cursor, copilot, "
                    "agentsmd. Defaults to 'all' (every bundled provider) when omitted."
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
                    "Overwrites a 'foreign' or 'drifted' file/block instead of skipping it. "
                    "Presence-only: pass just '--force', not '--force true/false'."
                ),
            },
        ],
        "failure_codes": [
            {
                "code": "usage-error",
                "condition": (
                    "An unknown --provider or --skill value was given, or --target global was "
                    "combined with a provider that has no global-scope concept (anything but claude)."
                ),
            },
            {"code": "io-error", "condition": "A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.)."},
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        optional=("provider", "target", "path", "skill"),
        switches=("force",),
        aliases={"p": "provider", "t": "target", "s": "skill", "f": "force"},
    )
    providers = _split(flags.get("provider"))
    skills = _split(flags.get("skill"))
    return installer.install(
        target_dir=flags.get("path", "."),
        providers=providers,
        skills=skills,
        scope=flags.get("target", "project"),
        force=flags.get("force", False),
    )


def _split(value):
    if value is None:
        return ["all"]
    return [v.strip() for v in value.split(",") if v.strip()]
