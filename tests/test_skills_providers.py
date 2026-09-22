"""Round 32, Class I: asserts each provider's wrap_* function content, not
just that a file exists at the right path -- before this, swapping two
wrap_* functions (e.g. wrap_claude for wrap_cursor) would have passed
every existing end-to-end installer test, since none of them checked the
generated content's actual shape."""

from adrpy.skills.providers import wrap_agentsmd_block, wrap_claude, wrap_copilot_stub, wrap_cursor

_META = {"description": "A test skill description."}


def test_wrap_claude_has_name_and_description_frontmatter():
    content = wrap_claude("my-skill", _META, "full body here", None)
    assert content.startswith("---\n")
    assert "name: my-skill\n" in content
    assert "description: A test skill description.\n" in content
    assert content.endswith("full body here")
    assert "alwaysApply" not in content


def test_wrap_cursor_has_description_and_always_apply_false():
    content = wrap_cursor("my-skill", _META, "full body here", None)
    assert content.startswith("---\n")
    assert "description: A test skill description.\n" in content
    assert "alwaysApply: false\n" in content
    assert content.endswith("full body here")
    assert "name: my-skill" not in content


def test_wrap_copilot_stub_points_at_shared_doc_not_full_body():
    content = wrap_copilot_stub("my-skill", _META, None, "doc/ai-skills/my-skill.md")
    assert "applyTo:" in content
    assert "A test skill description." in content
    assert "doc/ai-skills/my-skill.md" in content
    assert "full body here" not in content


def test_wrap_agentsmd_block_points_at_shared_doc_not_full_body():
    content = wrap_agentsmd_block("my-skill", _META, None, "doc/ai-skills/my-skill.md")
    assert "A test skill description." in content
    assert "doc/ai-skills/my-skill.md" in content
    assert "full body here" not in content
    # This is the block's own inner content, not the wrapping start/end
    # tags -- those are added by installer._AGENTSMD_BLOCK_TEMPLATE.
    assert "adrpy:skills" not in content
