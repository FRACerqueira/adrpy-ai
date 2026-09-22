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
        assert "drifted" in result["warnings"][0]

    def test_remove_deletes_drifted_file_with_force(self, tmp_path):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        path = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        path.write_text(path.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", True)
        assert len(result["removed"]) == 1
        assert not path.exists()

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
