"""Per-provider delivery: how each AI-coding-agent provider receives a
bundled skill (full body vs. stub + one shared doc), and where its files
live. Split by each provider's own activation model -- see ADR009V01."""

SHARED_DOC_PATH = "doc/ai-skills/{name}.md"


def wrap_claude(name, meta, full_content, shared_doc_path):
    return f"---\nname: {name}\ndescription: {meta['description']}\n---\n\n{full_content}"


def wrap_cursor(name, meta, full_content, shared_doc_path):
    return f"---\ndescription: {meta['description']}\nalwaysApply: false\n---\n\n{full_content}"


def wrap_copilot_stub(name, meta, full_content, shared_doc_path):
    return (
        f'---\napplyTo: "**"\n---\n\n'
        f"# {name}\n\n{meta['description']}\n\n"
        f"See `{shared_doc_path}` for the full procedure.\n"
    )


def wrap_agentsmd_block(name, meta, full_content, shared_doc_path):
    return f"### {name}\n\n{meta['description']}\n\nSee `{shared_doc_path}` for the full procedure.\n"


def wrap_shared_doc(name, meta, full_content, shared_doc_path):
    """The one full, tool-agnostic copy that stub-mode providers (copilot,
    agentsmd) point at -- not itself provider-wrapped."""
    return f"# {name}\n\n{full_content}"


PROVIDERS = {
    "claude": {
        "mode": "full",
        "project_path": ".claude/skills/{name}/SKILL.md",
        "global_path": "~/.claude/skills/{name}/SKILL.md",
        "wrap": wrap_claude,
    },
    "cursor": {
        "mode": "full",
        "project_path": ".cursor/rules/{name}.mdc",
        "global_path": None,
        "wrap": wrap_cursor,
    },
    "copilot": {
        "mode": "stub",
        "project_path": ".github/instructions/{name}.instructions.md",
        "global_path": None,
        "wrap": wrap_copilot_stub,
    },
    "agentsmd": {
        "mode": "stub_block",
        "project_path": "AGENTS.md",
        "global_path": None,
        "wrap": wrap_agentsmd_block,
    },
}

ALL_PROVIDERS = tuple(PROVIDERS)
STUB_MODE_PROVIDERS = tuple(name for name, spec in PROVIDERS.items() if spec["mode"] in ("stub", "stub_block"))
