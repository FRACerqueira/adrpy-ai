"""Regenerates the generated part of every command reference page from the
command's own describe() contract.

Each page under doc/commands/ (adrpy) and doc/skills/ (adrpy-skills) has
one block between `<!-- generated:start -->` and `<!-- generated:end -->`:
the Description, Arguments and Failure codes sections, rendered from
describe(). Everything outside the markers (the title, the one-line
summary, the Example section) is written by hand and left alone.
tests/test_command_docs.py fails when a page's block differs from what
this script renders, or when a command has no page.

Usage: python scripts/generate_command_docs.py
(requires adrpy installed, e.g. `pip install -e ".[dev]"` -- see CONTRIBUTING.md)
"""

import re
import sys
from pathlib import Path

from adrpy.core.registry import COMMANDS
from adrpy.skills.registry import COMMANDS as SKILLS_COMMANDS

REPO_ROOT = Path(__file__).resolve().parent.parent
START = "<!-- generated:start -->"
END = "<!-- generated:end -->"
NOTICE = "<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->"

# (registry, directory of its pages)
PAGE_SETS = (
    (COMMANDS, REPO_ROOT / "doc" / "commands"),
    (SKILLS_COMMANDS, REPO_ROOT / "doc" / "skills"),
)

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _cell(text):
    """A table cell: one line, every pipe escaped."""
    return _UNESCAPED_PIPE.sub(r"\\|", " ".join(str(text).split()))


def _argument_name(argument):
    if argument.get("positional"):
        return f"`{argument['name']}` (positional)"
    return f"`--{argument['name']}`"


def render(info):
    """The generated block (markers included) for one describe() result."""
    lines = [START, NOTICE, "", "## Description", "", info["description"].strip(), "", "## Arguments", ""]
    if info["arguments"]:
        lines += ["| Argument | Alias | Required | Type | Description |", "|---|---|---|---|---|"]
        for argument in info["arguments"]:
            alias = f"`{argument['alias']}`" if argument.get("alias") else "--"
            required = "yes" if argument["required"] else "no"
            lines.append(
                f"| {_argument_name(argument)} | {alias} | {required} | {argument['type']} | "
                f"{_cell(argument['description'])} |"
            )
    else:
        lines.append("None.")
    lines += ["", "## Failure codes", "", "| Code | Condition |", "|---|---|"]
    for entry in info["failure_codes"]:
        lines.append(f"| `{entry['code']}` | {_cell(entry['condition'])} |")
    lines.append(END)
    return "\n".join(lines)


def extract(text):
    """The generated block of a page (markers included), or None when the
    page does not have exactly one start and one end marker, in order."""
    if text.count(START) != 1 or text.count(END) != 1:
        return None
    start = text.index(START)
    end = text.index(END)
    if end < start:
        return None
    return text[start : end + len(END)]


def pages():
    """(command name, describe() result, page path) for every command."""
    for registry, directory in PAGE_SETS:
        for name, module in registry.items():
            yield name, module.describe(), directory / f"{name}.md"


def main():
    problems = []
    changed = 0
    for name, info, path in pages():
        if not path.is_file():
            problems.append(f"{name}: no page at {path}")
            continue
        text = path.read_text(encoding="utf-8")
        block = extract(text)
        if block is None:
            problems.append(f"{path}: needs exactly one {START} ... {END} block")
            continue
        rendered = render(info)
        if block != rendered:
            path.write_bytes(text.replace(block, rendered).encode("utf-8"))
            changed += 1
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"Regenerated {changed} page(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
