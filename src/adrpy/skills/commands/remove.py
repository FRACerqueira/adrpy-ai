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
            "deleted, even if this empties it. A 'foreign' file/block (no adrpy-skills marker at "
            "all -- a naming collision, or hand-written content) or a 'drifted' one (marker present "
            "but the content no longer matches it) is skipped, not deleted, unless --force is given "
            "-- reported in `skipped`, not as a failure. Asking to remove something not currently "
            "installed is reported in `warnings`, also not a failure. The one shared doc a "
            "stub-mode provider (copilot, agentsmd) points at is removed only once no remaining "
            "stub-mode provider in this same target still references it, and is itself subject to "
            "the same foreign/drifted protection; removing a full-mode provider (claude, cursor) "
            "never touches it. --target global combined with any provider other than claude fails "
            "with usage-error, checked before any write for the whole call, not per-provider."
        ),
        "arguments": [
            {
                "name": "provider",
                "alias": "-p",
                "type": "string",
                "required": False,
                "description": "Comma-separated list of providers to remove from: claude, cursor, copilot, agentsmd. Defaults to 'all'.",
            },
            {
                "name": "skill",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": f"Comma-separated list of skills to remove: {', '.join(SKILL_NAMES)}. Defaults to 'all'.",
            },
            {
                "name": "target",
                "alias": "-t",
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
                "alias": "-f",
                "type": "switch",
                "required": False,
                "description": "Removes a 'drifted' or 'foreign' file/block instead of skipping it. Presence-only.",
            },
        ],
        "failure_codes": [
            {
                "code": "usage-error",
                "condition": (
                    "An unknown --provider, --skill, or --target value was given (--target accepts only "
                    "'project'/'global'), or --target global was combined with a provider that has no "
                    "global-scope concept (anything but claude)."
                ),
            },
            {"code": "io-error", "condition": "A write/delete failed for a reason not covered by a more specific code (permission denied, etc.)."},
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        optional=("provider", "target", "path", "skill"),
        switches=("force",),
        aliases={"p": "provider", "t": "target", "s": "skill", "f": "force"},
    )
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
