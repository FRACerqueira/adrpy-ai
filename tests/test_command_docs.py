"""Every command reference page carries the block
scripts/generate_command_docs.py renders from the command's describe():
a page that drifted from its command, or a command with no page, fails
here. Run the script to bring the pages back in step."""

import copy
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_command_docs.py"
_spec = importlib.util.spec_from_file_location("generate_command_docs", _SCRIPT)
generate_command_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_command_docs)


def test_every_command_has_a_page_with_one_generated_block():
    for name, _info, path in generate_command_docs.pages():
        assert path.is_file(), f"{name} has no page at {path}"
        text = path.read_text(encoding="utf-8")
        assert generate_command_docs.extract(text) is not None, f"{path} has no single generated block"


def test_no_command_page_is_left_without_a_command():
    """A page for a command that no longer exists (renamed or removed)
    would keep documenting it: only INDEX/README pages may exist beside
    the generated ones."""
    known = {path.resolve() for _name, _info, path in generate_command_docs.pages()}
    folders = {path.parent for path in known}
    orphans = [
        page
        for folder in folders
        for page in sorted(folder.glob("*.md"))
        if page.resolve() not in known and page.stem.upper() not in ("INDEX", "README")
    ]
    assert orphans == []


def test_every_page_matches_what_describe_renders():
    for _name, info, path in generate_command_docs.pages():
        block = generate_command_docs.extract(path.read_text(encoding="utf-8"))
        assert block == generate_command_docs.render(info), (
            f"{path} drifted from describe(); run scripts/generate_command_docs.py"
        )


def test_the_comparison_detects_a_deliberate_drift():
    """Positive control: a changed failure-code condition, argument or
    description renders a different block than the page carries."""
    name, info, path = next(generate_command_docs.pages())
    block = generate_command_docs.extract(path.read_text(encoding="utf-8"))
    for mutate in (
        lambda d: d["failure_codes"][0].update(condition=d["failure_codes"][0]["condition"] + " (changed)"),
        lambda d: d["arguments"].pop(),
        lambda d: d.update(description=d["description"] + " Changed."),
    ):
        drifted = copy.deepcopy(info)
        mutate(drifted)
        assert generate_command_docs.render(drifted) != block, f"{name}: a drift went unnoticed"


def test_a_pipe_in_a_table_cell_is_escaped_once():
    info = {
        "description": "d",
        "arguments": [{"name": "x", "type": "string", "required": False, "description": "a | b and `\\|`"}],
        "failure_codes": [{"code": "c", "condition": "one | two"}],
    }
    rendered = generate_command_docs.render(info)
    assert "a \\| b and `\\|`" in rendered
    assert "one \\| two" in rendered


def test_a_page_without_markers_or_with_two_blocks_is_not_accepted():
    start, end = generate_command_docs.START, generate_command_docs.END
    assert generate_command_docs.extract("no markers") is None
    assert generate_command_docs.extract(f"{start}\n{end}\n{start}\n{end}") is None
    assert generate_command_docs.extract(f"{end}\n{start}") is None
