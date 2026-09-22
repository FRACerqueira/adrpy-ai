"""`remove` command: deletes/strips the requested (provider, skill) pairs,
same drift protection as `install` -- see ADR009V01."""

from adrpy.core.args import parse_flags
from adrpy.skills import installer
from adrpy.skills.resources import SKILL_NAMES


def describe():
    return {
        "name": "remove",
        "summary": "Removes one or more bundled skills for one or more AI-coding-agent providers.",
        "description": (
            "Deletes the requested (provider, skill) pairs, or -- for agentsmd -- strips only that "
            "skill's own marked block from AGENTS.md, leaving the rest of the file (the project "
            "owner's own content, other skills' blocks) untouched; AGENTS.md itself is never "
            "deleted, even if this empties it. A 'drifted' file/block (hand-edited since it was "
            "generated) is skipped, not deleted, unless --force is given -- reported as a warning, "
            "not a failure. Asking to remove something not currently installed is also a warning, "
            "not a failure. The one shared doc a stub-mode provider (copilot, agentsmd) points at "
            "is removed only once no remaining stub-mode provider in this same target still "
            "references it; removing a full-mode provider (claude, cursor) never touches it. "
            "--target global combined with any provider other than claude fails with usage-error."
        ),
        "arguments": [
            {
                "name": "provider",
                "type": "string",
                "required": False,
                "description": "Comma-separated list of providers to remove from: claude, cursor, copilot, agentsmd. Defaults to 'all'.",
            },
            {
                "name": "skill",
                "type": "string",
                "required": False,
                "description": f"Comma-separated list of skills to remove: {', '.join(SKILL_NAMES)}. Defaults to 'all'.",
            },
            {
                "name": "target",
                "type": "string",
                "required": False,
                "description": "'project' (default) or 'global' (claude only -- every other provider fails with usage-error).",
            },
            {
                "name": "path",
                "type": "string",
                "required": False,
                "description": "Repository root to remove from. Defaults to '.'. Only meaningful for --target project.",
            },
            {
                "name": "force",
                "type": "switch",
                "required": False,
                "description": "Removes a 'drifted' file/block instead of skipping it. Presence-only.",
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
            {"code": "io-error", "condition": "A write/delete failed for a reason not covered by a more specific code (permission denied, etc.)."},
        ],
    }


def run(args):
    flags = parse_flags(args, optional=("provider", "target", "path", "skill"), switches=("force",))
    return installer.remove(
        target_dir=flags.get("path", "."),
        providers=_split(flags.get("provider")),
        skills=_split(flags.get("skill")),
        scope=flags.get("target", "project"),
        force=flags.get("force", False),
    )


def _split(value):
    if value is None:
        return ["all"]
    return [v.strip() for v in value.split(",") if v.strip()]
