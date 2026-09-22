"""Loads each bundled skill's static resource files (gate.md, body.md,
glue.md, meta.json) from the package, and assembles the "full content" a
Claude-Code/Cursor-style provider receives, or a stub-mode provider's
shared doc gets."""

import json
from importlib import resources

SKILL_NAMES = ("comment-audit", "decision-log", "pre-release-audit")


def _read_optional(skill_name, filename):
    ref = resources.files("adrpy.resources.skills") / skill_name / filename
    if not ref.is_file():
        return None
    return ref.read_text(encoding="utf-8")


def load_meta(skill_name):
    text = _read_optional(skill_name, "meta.json")
    if text is None:
        raise FileNotFoundError(f"No meta.json bundled for skill '{skill_name}'.")
    return json.loads(text)


def load_full_content(skill_name):
    """gate.md (if present) + body.md + glue.md (if present), in that
    order -- when-to-run before how-to-do-it, then the project-specific
    instantiation. Matches how a human should read it cold."""
    parts = []
    gate = _read_optional(skill_name, "gate.md")
    if gate is not None:
        parts.append(gate.rstrip("\n"))
    body = _read_optional(skill_name, "body.md")
    if body is None:
        raise FileNotFoundError(f"No body.md bundled for skill '{skill_name}'.")
    parts.append(body.rstrip("\n"))
    glue = _read_optional(skill_name, "glue.md")
    if glue is not None:
        parts.append(glue.rstrip("\n"))
    return "\n\n".join(parts) + "\n"
