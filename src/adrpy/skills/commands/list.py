"""`list` command: read-only report of what's installed where -- see
ADR009V01."""

from adrpy.core.args import parse_flags
from adrpy.skills import installer
from adrpy.skills.resources import RETIRED_SKILL_NAMES, SKILL_NAMES


def describe():
    return {
        "name": "list",
        "summary": "Reports which bundled skills are installed, for which providers, and whether any have drifted.",
        "description": (
            "Reports, for every requested skill and provider, whether it is installed, whether it has drifted"
            " (null when not installed; true for a foreign, hand-edited or malformed file or block) and the "
            "resolved path; claude is reported in both project and global scope. A stub-mode provider adds "
            "one `shared-doc` row per skill. Read-only: it computes hashes but never writes."
        ),
        "arguments": [
            {
                "name": "provider",
                "alias": "-p",
                "type": "string",
                "required": False,
                "description": "Comma-separated list of providers to report on: claude, cursor, copilot, agentsmd. Defaults to 'all'.",
            },
            {
                "name": "skill",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    f"Comma-separated list of skills to report on: {', '.join(SKILL_NAMES)}, or one no longer shipped "
                    f"that an older version installed ({', '.join(RETIRED_SKILL_NAMES)}). Defaults to 'all', which "
                    "lists a no-longer-shipped skill only where it is still installed."
                ),
            },
            {
                "name": "path",
                "type": "string",
                "required": False,
                "description": "Repository root to inspect for project-scope entries. Defaults to '.'.",
            },
        ],
        "failure_codes": [
            {"code": "target-directory-not-found", "condition": "--path does not point to an existing directory (never created) -- nothing was written."},
            {"code": "usage-error", "condition": "An unknown --provider or --skill value was given."},
            {"code": "io-error", "condition": "A read failed (permission denied, a file over the 10MB read limit, or a file that is not valid UTF-8 -- the detail names it)."},
        ],
    }


def run(args):
    flags = parse_flags(args, optional=("provider", "path", "skill"), aliases={"p": "provider", "s": "skill"})
    return installer.list_installed(
        target_dir=flags.get("path", "."),
        providers=_split(flags.get("provider")),
        skills=_split(flags.get("skill")),
    )


def _split(value):
    if value is None:
        return ["all"]
    return [v.strip() for v in value.split(",") if v.strip()]
