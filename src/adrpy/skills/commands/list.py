"""`list` command: read-only report of what's installed where -- see
ADR009V01."""

from adrpy.core.args import parse_flags
from adrpy.skills import installer
from adrpy.skills.resources import SKILL_NAMES


def describe():
    return {
        "name": "list",
        "summary": "Reports which bundled skills are installed, for which providers, and whether any have drifted.",
        "description": (
            "Cross-product of every requested skill x every requested provider, each entry "
            "reporting installed (bool), drifted (null when not installed; otherwise true if the "
            "file/block is either 'foreign' -- no adrpy-skills marker, meaning install/remove would "
            "refuse to touch it without --force -- or genuinely hand-edited since it was generated; "
            "false only when the content still matches exactly what was last generated), and the "
            "resolved file path either way. Always reports both project and global scope for claude "
            "(the only provider with a global-scope concept); every other provider is project-scope "
            "only. Read-only in the strict sense: computes a hash to determine drift, but never "
            "writes anything back, regardless of what it finds."
        ),
        "arguments": [
            {
                "name": "provider",
                "type": "string",
                "required": False,
                "description": "Comma-separated list of providers to report on: claude, cursor, copilot, agentsmd. Defaults to 'all'.",
            },
            {
                "name": "skill",
                "type": "string",
                "required": False,
                "description": f"Comma-separated list of skills to report on: {', '.join(SKILL_NAMES)}. Defaults to 'all'.",
            },
            {
                "name": "path",
                "type": "string",
                "required": False,
                "description": "Repository root to inspect for project-scope entries. Defaults to '.'.",
            },
        ],
        "failure_codes": [
            {"code": "usage-error", "condition": "An unknown --provider or --skill value was given."},
            {"code": "io-error", "condition": "A read failed for a reason not covered by a more specific code (permission denied, etc.)."},
        ],
    }


def run(args):
    flags = parse_flags(args, optional=("provider", "path", "skill"))
    return installer.list_installed(
        target_dir=flags.get("path", "."),
        providers=_split(flags.get("provider")),
        skills=_split(flags.get("skill")),
    )


def _split(value):
    if value is None:
        return ["all"]
    return [v.strip() for v in value.split(",") if v.strip()]
