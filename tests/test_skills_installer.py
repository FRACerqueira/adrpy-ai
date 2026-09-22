import time
from pathlib import Path

from adrpy.core.errors import UsageError
from adrpy.core.hashing import check_drift
from adrpy.skills import installer

import pytest


def _hand_edit_inside_marker(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


_PROJECT_PATHS = {
    "claude": ".claude/skills/{name}/SKILL.md",
    "cursor": ".cursor/rules/{name}.mdc",
    "copilot": ".github/instructions/{name}.instructions.md",
}


def _installed_path(tmp_path, provider, skill_name="pre-release-audit"):
    return tmp_path / _PROJECT_PATHS[provider].format(name=skill_name)


class TestInstallBasic:
    def test_install_writes_all_four_providers(self, tmp_path):
        result = installer.install(str(tmp_path), ["all"], ["pre-release-audit"], "project", False)
        assert {row["provider"] for row in result["installed"]} == {"claude", "cursor", "copilot", "agentsmd"}
        assert result["skipped"] == []
        assert (tmp_path / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").exists()
        assert (tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc").exists()
        assert (tmp_path / ".github" / "instructions" / "pre-release-audit.instructions.md").exists()
        assert (tmp_path / "AGENTS.md").exists()
        # Stub-mode providers share one full copy; full-mode providers don't need it.
        assert (tmp_path / "doc" / "ai-skills" / "pre-release-audit.md").exists()

    def test_default_args_install_all_skills_and_providers(self, tmp_path):
        result = installer.install(str(tmp_path), ["all"], ["all"], "project", False)
        installed_pairs = {(row["provider"], row["skill"]) for row in result["installed"]}
        assert len(installed_pairs) == 4 * 3  # 4 providers x 3 skills

    def test_comment_audit_has_no_gate_and_still_installs(self, tmp_path):
        result = installer.install(str(tmp_path), ["claude"], ["comment-audit"], "project", False)
        assert result["skipped"] == []
        content = (tmp_path / ".claude" / "skills" / "comment-audit" / "SKILL.md").read_text(encoding="utf-8")
        assert "# Comment audit" in content


class TestMarkerRoundTrip:
    def test_marker_hash_matches_a_fresh_recompute_of_the_body(self, tmp_path):
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "project", False)
        content = (tmp_path / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").read_text(encoding="utf-8")
        assert check_drift(content) == "clean"

    def test_reinstall_with_no_changes_is_clean_not_drifted(self, tmp_path):
        installer.install(str(tmp_path), ["all"], ["pre-release-audit"], "project", False)
        result = installer.install(str(tmp_path), ["all"], ["pre-release-audit"], "project", False)
        assert result["skipped"] == []
        assert {row["provider"] for row in result["installed"]} == {"claude", "cursor", "copilot", "agentsmd"}

    def test_marker_is_placed_after_frontmatter_not_before(self, tmp_path):
        # Round 32, Class I: the marker's exact position was never asserted
        # directly (only that the round-trip hash is "clean", which would
        # still pass if the marker were misplaced but self-consistent).
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "project", False)
        content = (tmp_path / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").read_text(encoding="utf-8")
        assert not content.startswith("<!-- adrpy-skills:")
        frontmatter_end = content.index("---\n", 4) + len("---\n")
        assert content[frontmatter_end:].startswith("<!-- adrpy-skills:")


class TestDriftProtection:
    @pytest.mark.parametrize("provider", ["claude", "cursor", "copilot"])
    def test_hand_edited_full_or_stub_file_is_skipped_without_force(self, tmp_path, provider):
        installer.install(str(tmp_path), [provider], ["pre-release-audit"], "project", False)
        path = _installed_path(tmp_path, provider)
        # Corrupt content inside the marker's own hashed region.
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.install(str(tmp_path), [provider], ["pre-release-audit"], "project", False)
        assert result["installed"] == []
        assert result["skipped"][0]["reason"] == "drifted"
        assert "HAND EDITED" in path.read_text(encoding="utf-8")

    @pytest.mark.parametrize("provider", ["claude", "cursor", "copilot"])
    def test_hand_edited_file_is_overwritten_with_force(self, tmp_path, provider):
        installer.install(str(tmp_path), [provider], ["pre-release-audit"], "project", False)
        path = _installed_path(tmp_path, provider)
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.install(str(tmp_path), [provider], ["pre-release-audit"], "project", True)
        assert result["skipped"] == []
        assert len(result["installed"]) == 1
        assert "HAND EDITED" not in path.read_text(encoding="utf-8")

    def test_hand_edited_shared_doc_is_skipped_on_install_without_force(self, tmp_path):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.write_text(shared.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        reasons = {row["reason"] for row in result["skipped"] if row["provider"] == "shared-doc"}
        assert "drifted" in reasons
        assert "HAND EDITED" in shared.read_text(encoding="utf-8")

    def test_hand_edited_shared_doc_is_overwritten_on_install_with_force(self, tmp_path):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.write_text(shared.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", True)
        assert "HAND EDITED" not in shared.read_text(encoding="utf-8")

    def test_hand_edited_shared_doc_is_skipped_on_remove_without_force(self, tmp_path):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.write_text(shared.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        assert shared.exists()
        reasons = {row["reason"] for row in result["skipped"] if row["provider"] == "shared-doc"}
        assert "drifted" in reasons

    def test_agentsmd_block_drift_is_isolated_per_skill(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        _hand_edit_inside_marker(agents_md, "### pre-release-audit", "### pre-release-audit (EDITED)")

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"], "project", False)
        skipped_skills = {row["skill"] for row in result["skipped"]}
        installed_skills = {row["skill"] for row in result["installed"]}
        assert skipped_skills == {"pre-release-audit"}
        assert installed_skills == {"decision-log"}
        # The hand-edit survives because that block was skipped, not overwritten.
        assert "(EDITED)" in agents_md.read_text(encoding="utf-8")

    def test_foreign_file_is_skipped_without_force(self, tmp_path):
        target = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("hand-written, never generated by this tool", encoding="utf-8")

        result = installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert result["installed"] == []
        assert result["skipped"][0]["reason"] == "foreign"
        assert target.read_text(encoding="utf-8") == "hand-written, never generated by this tool"

    def test_foreign_file_is_overwritten_with_force(self, tmp_path):
        target = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("hand-written, never generated by this tool", encoding="utf-8")

        result = installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", True)
        assert len(result["installed"]) == 1
        assert "hand-written" not in target.read_text(encoding="utf-8")


class TestRemove:
    def test_remove_deletes_the_file(self, tmp_path):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        path = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        assert path.exists()
        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert len(result["removed"]) == 1
        assert not path.exists()

    def test_remove_not_installed_is_a_warning_not_an_error(self, tmp_path):
        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert result["removed"] == []
        assert "not installed" in result["warnings"][0]

    def test_remove_skips_drifted_file_without_force(self, tmp_path):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        path = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        path.write_text(path.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert result["removed"] == []
        assert path.exists()
        assert result["skipped"][0]["reason"] == "drifted"

    def test_remove_deletes_drifted_file_with_force(self, tmp_path):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        path = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        path.write_text(path.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", True)
        assert len(result["removed"]) == 1
        assert not path.exists()

    def test_agentsmd_drifted_block_is_skipped_on_remove_without_force(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        _hand_edit_inside_marker(agents_md, "### pre-release-audit", "### pre-release-audit (EDITED)")

        result = installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        assert result["removed"] == []
        assert result["skipped"][0]["reason"] == "drifted"
        assert "(EDITED)" in agents_md.read_text(encoding="utf-8")

    def test_agentsmd_drifted_block_is_removed_with_force(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        _hand_edit_inside_marker(agents_md, "### pre-release-audit", "### pre-release-audit (EDITED)")

        result = installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", True)
        # Also removes the shared doc: this was the only stub-mode provider
        # still referencing it.
        assert any(row["provider"] == "agentsmd" for row in result["removed"])
        assert "adrpy:skills:pre-release-audit" not in agents_md.read_text(encoding="utf-8")

    def test_agentsmd_removal_strips_only_its_own_block(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        before = agents_md.read_text(encoding="utf-8")
        assert "pre-release-audit" in before and "decision-log" in before

        installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        after = agents_md.read_text(encoding="utf-8")
        assert "adrpy:skills:pre-release-audit" not in after
        assert "adrpy:skills:decision-log" in after
        # Never delete AGENTS.md itself, even partially emptied.
        assert agents_md.exists()

    def test_agentsmd_file_never_deleted_even_when_last_block_removed(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        assert agents_md.exists()

    def test_preexisting_agentsmd_content_survives_install_and_removal(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# My project\n\nSome hand-written instructions.\n", encoding="utf-8")

        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        mid = agents_md.read_text(encoding="utf-8")
        assert "Some hand-written instructions." in mid
        assert "pre-release-audit" in mid

        installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        after = agents_md.read_text(encoding="utf-8")
        assert "Some hand-written instructions." in after
        assert "adrpy:skills:pre-release-audit" not in after


class TestSharedDocLifecycle:
    def test_shared_doc_survives_while_another_stub_provider_still_references_it(self, tmp_path):
        installer.install(str(tmp_path), ["copilot", "agentsmd"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        assert shared.exists()

        installer.remove(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        assert shared.exists()  # agentsmd still references it

        installer.remove(str(tmp_path), ["agentsmd"], ["comment-audit"], "project", False)
        assert not shared.exists()  # nothing references it anymore

    def test_removing_full_mode_provider_never_touches_shared_doc(self, tmp_path):
        installer.install(str(tmp_path), ["claude", "copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        assert shared.exists()
        installer.remove(str(tmp_path), ["claude"], ["comment-audit"], "project", False)
        assert shared.exists()


class TestList:
    def test_list_reports_accurate_installed_state(self, tmp_path):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        rows = installer.list_installed(str(tmp_path), ["cursor"], ["pre-release-audit", "decision-log"])["skills"]
        by_skill = {row["skill"]: row for row in rows}
        assert by_skill["pre-release-audit"]["installed"] is True
        assert by_skill["pre-release-audit"]["drifted"] is False
        assert by_skill["decision-log"]["installed"] is False
        assert by_skill["decision-log"]["drifted"] is None

    def test_list_never_writes_anything(self, tmp_path):
        installer.list_installed(str(tmp_path), ["all"], ["all"])
        assert list(tmp_path.rglob("*")) == []

    def test_list_flags_foreign_file_as_drifted(self, tmp_path):
        target = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("hand-written", encoding="utf-8")
        rows = installer.list_installed(str(tmp_path), ["cursor"], ["pre-release-audit"])["skills"]
        assert rows[0]["installed"] is True
        assert rows[0]["drifted"] is True

    def test_list_includes_both_scopes_for_claude(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        (tmp_path / "home").mkdir()
        rows = installer.list_installed(str(tmp_path), ["claude"], ["pre-release-audit"])["skills"]
        scopes = {row["scope"] for row in rows}
        assert scopes == {"project", "global"}

    def test_list_always_returns_a_warnings_key(self, tmp_path):
        # Round 32, Class E: every response -- including this read-only one
        # -- carries `warnings`, even empty, matching the cross-command
        # guarantee cli/explore.py and cli/help.py already document.
        result = installer.list_installed(str(tmp_path), ["all"], ["all"])
        assert result["warnings"] == []

    def test_list_reports_agentsmd_installed_state(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        rows = installer.list_installed(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"])["skills"]
        by_skill = {row["skill"]: row for row in rows}
        assert by_skill["pre-release-audit"]["installed"] is True
        assert by_skill["pre-release-audit"]["drifted"] is False
        assert by_skill["decision-log"]["installed"] is False
        assert by_skill["decision-log"]["drifted"] is None

    def test_list_flags_malformed_agentsmd_block_as_drifted(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n",
            encoding="utf-8",
        )
        rows = installer.list_installed(str(tmp_path), ["agentsmd"], ["pre-release-audit"])["skills"]
        assert rows[0]["installed"] is True
        assert rows[0]["drifted"] is True


class TestGlobalScope:
    def test_global_scope_writes_under_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "global", False)
        assert (home / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").exists()
        assert not (tmp_path / ".claude").exists()

    @pytest.mark.parametrize("provider", ["cursor", "copilot", "agentsmd"])
    def test_global_scope_rejected_for_providers_without_a_global_concept(self, tmp_path, provider):
        with pytest.raises(UsageError):
            installer.install(str(tmp_path), [provider], ["pre-release-audit"], "global", False)
        assert list(tmp_path.rglob("*")) == []

    @pytest.mark.parametrize("provider", ["cursor", "copilot", "agentsmd"])
    def test_global_scope_rejected_on_remove_too(self, tmp_path, provider):
        with pytest.raises(UsageError):
            installer.remove(str(tmp_path), [provider], ["pre-release-audit"], "global", False)


class TestUnknownValues:
    def test_unknown_provider_raises_usage_error(self, tmp_path):
        with pytest.raises(UsageError):
            installer.install(str(tmp_path), ["not-a-real-provider"], ["pre-release-audit"], "project", False)

    def test_unknown_skill_raises_usage_error(self, tmp_path):
        with pytest.raises(UsageError):
            installer.install(str(tmp_path), ["claude"], ["not-a-real-skill"], "project", False)

    def test_unknown_value_error_lists_the_valid_options(self, tmp_path):
        with pytest.raises(UsageError, match="claude"):
            installer.install(str(tmp_path), ["not-a-real-provider"], ["pre-release-audit"], "project", False)

    def test_duplicate_values_are_deduplicated(self, tmp_path):
        result = installer.install(str(tmp_path), ["cursor", "cursor"], ["pre-release-audit"], "project", False)
        assert len(result["installed"]) == 1

    def test_empty_value_list_after_split_is_a_usage_error(self, tmp_path):
        # Distinct from omitting the flag entirely (which defaults to "all"):
        # an explicit but empty value (e.g. "--provider ,") must not silently
        # fall back to "all" -- that would widen the blast radius of any
        # accidental mistake to every provider/skill instead of erroring.
        with pytest.raises(UsageError):
            installer.install(str(tmp_path), [], ["pre-release-audit"], "project", False)


class TestRemoveForeignProtection:
    """Round 32, Class A: remove() must refuse to touch a 'foreign' file
    or block (no adrpy-skills marker at all) exactly like install() already
    does -- previously it only checked for 'drifted', so a hand-written
    file colliding with a skill's install path (e.g. a real, hand-authored
    ~/.claude/skills/<name>/SKILL.md predating any adrpy-skills install)
    was deleted unconditionally, with no warning, even without --force."""

    def test_remove_skips_foreign_file_without_force(self, tmp_path):
        target = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("hand-written, never generated by this tool", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert result["removed"] == []
        assert result["skipped"][0]["reason"] == "foreign"
        assert target.read_text(encoding="utf-8") == "hand-written, never generated by this tool"

    def test_remove_deletes_foreign_file_with_force(self, tmp_path):
        target = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("hand-written, never generated by this tool", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", True)
        assert len(result["removed"]) == 1
        assert not target.exists()

    def test_remove_global_claude_skips_hand_written_file_without_force(self, tmp_path, monkeypatch):
        # Reproduces the release-blocking scenario found by the Round 32
        # filesystem-security front: `adrpy-skills remove --provider claude
        # --target global` with no other flags must never delete a real,
        # hand-authored ~/.claude/skills/<name>/SKILL.md.
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        skill_path = home / ".claude" / "skills" / "pre-release-audit" / "SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("hand-written skill file, never installed by adrpy-skills", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["claude"], ["pre-release-audit"], "global", False)
        assert result["removed"] == []
        assert skill_path.exists()
        assert "hand-written" in skill_path.read_text(encoding="utf-8")

    def test_remove_skips_foreign_agentsmd_block_without_force(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\n"
            "Hand-written block, never generated by this tool.\n"
            "<!-- adrpy:skills:pre-release-audit:end -->\n",
            encoding="utf-8",
        )
        result = installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        assert result["removed"] == []
        assert result["skipped"][0]["reason"] == "foreign"
        assert "Hand-written block" in agents_md.read_text(encoding="utf-8")

    def test_remove_strips_foreign_agentsmd_block_with_force(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\n"
            "Hand-written block, never generated by this tool.\n"
            "<!-- adrpy:skills:pre-release-audit:end -->\n",
            encoding="utf-8",
        )
        result = installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", True)
        assert len(result["removed"]) == 1
        assert "Hand-written block" not in agents_md.read_text(encoding="utf-8")

    def test_remove_never_deletes_a_foreign_shared_doc(self, tmp_path):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.write_text("hand-written shared doc, not generated by this tool", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        assert shared.exists()
        assert shared.read_text(encoding="utf-8") == "hand-written shared doc, not generated by this tool"
        reasons = {row["reason"] for row in result["skipped"] if row["provider"] == "shared-doc"}
        assert "foreign" in reasons

    def test_remove_deletes_a_foreign_shared_doc_with_force(self, tmp_path):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.write_text("hand-written shared doc, not generated by this tool", encoding="utf-8")

        installer.remove(str(tmp_path), ["copilot"], ["comment-audit"], "project", True)
        assert not shared.exists()


class TestAgentsmdMalformedBlocks:
    """Round 32, Class C: AGENTS.md block parsing must recognize -- and
    refuse to silently touch -- a truncated block (a 'start' tag with no
    matching 'end') and a duplicated block (more than one complete pair
    for the same skill), instead of either silently appending a second,
    conflicting block or only ever touching the first of two copies."""

    def test_truncated_block_is_reported_as_malformed_by_install(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n",
            encoding="utf-8",
        )
        before = agents_md.read_text(encoding="utf-8")

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        assert result["installed"] == []
        assert result["skipped"][0]["reason"] == "malformed"
        assert agents_md.read_text(encoding="utf-8") == before

    def test_truncated_block_is_reported_as_malformed_by_remove(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n",
            encoding="utf-8",
        )
        result = installer.remove(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        assert result["removed"] == []
        assert result["skipped"][0]["reason"] == "malformed"

    def test_duplicated_block_is_reported_as_malformed(self, tmp_path):
        block = (
            "<!-- adrpy:skills:pre-release-audit:start -->\nfirst copy\n"
            "<!-- adrpy:skills:pre-release-audit:end -->\n"
            "<!-- adrpy:skills:pre-release-audit:start -->\nsecond, stale copy\n"
            "<!-- adrpy:skills:pre-release-audit:end -->\n"
        )
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(block, encoding="utf-8")

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", False)
        assert result["installed"] == []
        assert result["skipped"][0]["reason"] == "malformed"
        # Neither copy was touched -- an untested "fix" that patched only
        # the first match would have left the second permanently stale.
        assert agents_md.read_text(encoding="utf-8") == block

    def test_malformed_block_can_still_be_overwritten_with_force(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n",
            encoding="utf-8",
        )
        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", True)
        assert len(result["installed"]) == 1
        from adrpy.core.hashing import check_drift

        inner = installer._agentsmd_extract_inner(agents_md.read_text(encoding="utf-8"), "pre-release-audit")
        assert check_drift(inner) == "clean"

    def test_force_cleanup_of_truncated_block_never_deletes_another_skills_valid_block(self, tmp_path):
        # Round 34, re-verification finding: _agentsmd_force_strip_all used to
        # use a greedy regex from the orphaned :start tag to end-of-file when
        # no :end existed anywhere for that skill -- deleting everything past
        # it, including another skill's own still-valid, unrelated block.
        installer.install(str(tmp_path), ["agentsmd"], ["decision-log"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        before_decision_log = agents_md.read_text(encoding="utf-8")

        # Insert a truncated pre-release-audit block, with no :end tag, BEFORE
        # decision-log's own clean block, plus trailing hand-written notes.
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n"
            + before_decision_log
            + "Some trailing hand-written project notes that must survive.\n",
            encoding="utf-8",
        )

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", True)
        assert len(result["installed"]) == 1
        after = agents_md.read_text(encoding="utf-8")
        assert "adrpy:skills:decision-log" in after
        assert "Some trailing hand-written project notes that must survive." in after
        # decision-log's own block must still be exactly what it was -- not
        # just "present", genuinely unmodified.
        inner = installer._agentsmd_extract_inner(after, "decision-log")
        from adrpy.core.hashing import check_drift

        assert check_drift(inner) == "clean"

    def test_force_cleanup_of_duplicated_block_never_deletes_an_interleaved_skills_block(self, tmp_path):
        # Same root cause, the other malformed shape: a greedy start-to-LAST-end
        # regex used to swallow any other skill's block sitting between two
        # duplicate copies of the same skill's own block.
        duplicated = (
            "<!-- adrpy:skills:pre-release-audit:start -->\nfirst copy\n"
            "<!-- adrpy:skills:pre-release-audit:end -->\n"
            "<!-- adrpy:skills:decision-log:start -->\nSKILL-BODY-MARKER\n"
            "<!-- adrpy:skills:decision-log:end -->\n"
            "<!-- adrpy:skills:pre-release-audit:start -->\nsecond, stale copy\n"
            "<!-- adrpy:skills:pre-release-audit:end -->\n"
        )
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(duplicated, encoding="utf-8")

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", True)
        assert len(result["installed"]) == 1
        after = agents_md.read_text(encoding="utf-8")
        assert "SKILL-BODY-MARKER" in after
        assert "adrpy:skills:decision-log" in after


class TestGlobalScopeValidatedBeforeAnyWrite:
    """Round 32, Class D: --target global's per-provider validity check
    must run for every requested provider BEFORE any write begins -- not
    inside the per-provider loop, where an earlier provider in iteration
    order could already have written (install) or deleted (remove)
    something before a later provider triggers the usage-error."""

    def test_install_validates_every_provider_before_writing_any(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        with pytest.raises(UsageError):
            installer.install(str(tmp_path), ["claude", "cursor"], ["pre-release-audit"], "global", False)
        assert not (home / ".claude").exists()

    def test_remove_validates_every_provider_before_removing_any(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "global", False)
        skill_path = home / ".claude" / "skills" / "pre-release-audit" / "SKILL.md"
        assert skill_path.exists()

        with pytest.raises(UsageError):
            installer.remove(str(tmp_path), ["claude", "cursor"], ["pre-release-audit"], "global", False)
        assert skill_path.exists()


class TestAtomicWrites:
    """Round 32, Class B1: installer.py must not bypass the project-wide
    atomic_write.py convention -- a raw Path.write_text() call can leave a
    torn/empty file behind if interrupted mid-write, silently swallowed by
    the next `install` (which would see "absent" and write a fresh file
    over the loss without ever reporting it)."""

    def test_installer_never_calls_raw_write_text(self):
        import inspect

        source = inspect.getsource(installer)
        assert ".write_text(" not in source, "installer.py must route every write through atomic_write_text"


class TestRemoveTolerateVanishingFile:
    """Round 32, Class B2: remove()'s generic-provider branch must not
    raise if the target file disappears between the read (used for the
    drift check) and the unlink -- a classic check-then-use window that,
    before this fix, would abort the whole command (including any other
    (provider, skill) pairs still queued in the same call) instead of
    behaving like the rest of the project's best-effort-per-item writers."""

    def test_remove_tolerates_file_vanishing_between_read_and_unlink(self, tmp_path, monkeypatch):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        path = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        original_read_text = Path.read_text

        def read_then_vanish(self, *args, **kwargs):
            content = original_read_text(self, *args, **kwargs)
            if self == path and path.exists():
                path.unlink()
            return content

        monkeypatch.setattr(Path, "read_text", read_then_vanish)

        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert result["removed"] == [{"provider": "cursor", "skill": "pre-release-audit", "file": str(path)}]


class TestAgentsmdAdversarialContentStaysLinearTime:
    """Round 34, Security front: the prior per-skill DOTALL-based block
    regexes (`.*`/`.*?` scanning for a matching `:end`) cost O(n^2) against
    adversarial content with many `:start` tags and no matching `:end`
    anywhere -- measured ~9.5s against a 771KB crafted file, reachable even
    by the read-only `list` command (default --provider all includes
    agentsmd). The fix replaces per-skill DOTALL spans with one linear tag
    scan (no `.*`/DOTALL at all), so this must stay fast regardless of how
    many near-miss tags an adversarial AGENTS.md contains."""

    def test_many_unmatched_start_tags_stays_fast(self, tmp_path):
        # Same shape as the front's own repro: repeated :start tags for a
        # real skill name, no :end anywhere. A quadratic implementation
        # would already take several seconds at this size; a linear one
        # finishes near-instantly -- the threshold below is generous
        # specifically to avoid machine-speed flakiness while still being
        # far below what O(n^2) would need at this size.
        content = ("<!-- adrpy:skills:decision-log:start -->\n" + "x" * 200) * 3000
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(content, encoding="utf-8")

        started = time.monotonic()
        rows = installer.list_installed(str(tmp_path), ["agentsmd"], ["decision-log"])["skills"]
        elapsed = time.monotonic() - started

        assert elapsed < 3.0, f"list_installed took {elapsed:.2f}s against adversarial AGENTS.md content"
        assert rows[0]["installed"] is True
        assert rows[0]["drifted"] is True  # malformed: many starts, zero ends
