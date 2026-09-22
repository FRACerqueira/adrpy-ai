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
        # "shared-doc" is its own row now too -- copilot and agentsmd both
        # need it, but it's written (and reported) once per skill, not once
        # per provider.
        assert {row["provider"] for row in result["installed"]} == {"claude", "cursor", "copilot", "agentsmd", "shared-doc"}
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
        # 4 providers x 3 skills, plus 1 shared-doc row per skill.
        assert len(installed_pairs) == 4 * 3 + 3

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
        assert {row["provider"] for row in result["installed"]} == {
            "claude",
            "cursor",
            "copilot",
            "agentsmd",
            "shared-doc",
        }

    def test_marker_is_placed_after_frontmatter_not_before(self, tmp_path):
        # Round 32, Class I: the marker's exact position was never asserted
        # directly (only that the round-trip hash is "clean", which would
        # still pass if the marker were misplaced but self-consistent).
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "project", False)
        content = (tmp_path / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").read_text(encoding="utf-8")
        assert not content.startswith("<!-- adrpy-skills:")
        frontmatter_end = content.index("---\n", 4) + len("---\n")
        assert content[frontmatter_end:].startswith("<!-- adrpy-skills:")

    def test_unicode_content_round_trips_through_the_hash_and_agentsmd_tag_scan(self, tmp_path):
        # Round 35, Test-Adequacy front: no test exercised non-ASCII content
        # through the hash/marker round-trip or the AGENTS.md tag scan.
        # Confirms compute_hash's explicit UTF-8 encoding and the tag
        # regex's `[^:\n]+` name group both handle it correctly, not just
        # ASCII skill bodies.
        installer.install(str(tmp_path), ["claude", "agentsmd"], ["pre-release-audit"], "project", False)

        claude_path = tmp_path / ".claude" / "skills" / "pre-release-audit" / "SKILL.md"
        text = claude_path.read_text(encoding="utf-8")
        claude_path.write_text(text + "\nUnicode edit: café, naïve, 日本語, emoji 🎉\n", encoding="utf-8")
        assert check_drift(claude_path.read_text(encoding="utf-8")) == "drifted"

        agents_md = tmp_path / "AGENTS.md"
        _hand_edit_inside_marker(agents_md, "### pre-release-audit", "### pre-release-audit — café, 日本語 🎉")
        inner = installer._agentsmd_extract_inner(agents_md.read_text(encoding="utf-8"), "pre-release-audit")
        assert check_drift(inner) == "drifted"

        result = installer.install(str(tmp_path), ["claude", "agentsmd"], ["pre-release-audit"], "project", True)
        assert len(result["installed"]) == 3  # claude, agentsmd, and the shared-doc agentsmd needs
        assert check_drift(claude_path.read_text(encoding="utf-8")) == "clean"


class TestDriftProtection:
    @pytest.mark.parametrize("provider", ["claude", "cursor", "copilot"])
    def test_hand_edited_full_or_stub_file_is_skipped_without_force(self, tmp_path, provider):
        installer.install(str(tmp_path), [provider], ["pre-release-audit"], "project", False)
        path = _installed_path(tmp_path, provider)
        # Corrupt content inside the marker's own hashed region.
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.install(str(tmp_path), [provider], ["pre-release-audit"], "project", False)
        # For copilot, the (unrelated, clean) shared doc still installs
        # independently -- only the provider's own drifted row is absent.
        assert provider not in {row["provider"] for row in result["installed"]}
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
        assert provider in {row["provider"] for row in result["installed"]}
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

    def test_hand_edited_shared_doc_is_skipped_via_agentsmd_too(self, tmp_path):
        # Round 35, Test-Adequacy front: every shared-doc drift/foreign test
        # above used copilot -- agentsmd is the other stub-mode provider,
        # with its own, more complex reference-counting via
        # _other_stub_providers_reference, and had never triggered a
        # drift/foreign shared-doc scenario in any test.
        installer.install(str(tmp_path), ["agentsmd"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.write_text(shared.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        install_result = installer.install(str(tmp_path), ["agentsmd"], ["comment-audit"], "project", False)
        reasons = {row["reason"] for row in install_result["skipped"] if row["provider"] == "shared-doc"}
        assert "drifted" in reasons
        assert "HAND EDITED" in shared.read_text(encoding="utf-8")

        remove_result = installer.remove(str(tmp_path), ["agentsmd"], ["comment-audit"], "project", False)
        assert shared.exists()
        reasons = {row["reason"] for row in remove_result["skipped"] if row["provider"] == "shared-doc"}
        assert "drifted" in reasons

    def test_agentsmd_block_drift_is_isolated_per_skill(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        _hand_edit_inside_marker(agents_md, "### pre-release-audit", "### pre-release-audit (EDITED)")

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"], "project", False)
        # Filtered to the agentsmd provider itself -- the (unrelated,
        # clean) shared doc for pre-release-audit still installs
        # independently of its own agentsmd block being drifted.
        skipped_skills = {row["skill"] for row in result["skipped"] if row["provider"] == "agentsmd"}
        installed_skills = {row["skill"] for row in result["installed"] if row["provider"] == "agentsmd"}
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
        # The (unrelated, clean) shared doc still installs independently --
        # only the malformed agentsmd row is absent.
        assert "agentsmd" not in {row["provider"] for row in result["installed"]}
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
        assert "agentsmd" not in {row["provider"] for row in result["installed"]}
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
        assert "agentsmd" in {row["provider"] for row in result["installed"]}
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
        assert "agentsmd" in {row["provider"] for row in result["installed"]}
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
        assert "agentsmd" in {row["provider"] for row in result["installed"]}
        after = agents_md.read_text(encoding="utf-8")
        assert "SKILL-BODY-MARKER" in after
        assert "adrpy:skills:decision-log" in after

    def test_two_different_skills_malformed_in_the_same_call_are_detected_independently(self, tmp_path):
        # Round 35, Test-Adequacy front: every existing malformed-block test
        # uses a file containing only ONE skill's own (malformed) block --
        # this exercises detection for two DIFFERENT skills, both malformed,
        # in the same install() call, confirming AGENTS.md is re-read fresh
        # per skill_name rather than a status computed once and reused.
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n"
            "<!-- adrpy:skills:decision-log:start -->\nalso no matching end tag\n",
            encoding="utf-8",
        )

        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit", "decision-log"], "project", False)
        assert "agentsmd" not in {row["provider"] for row in result["installed"]}
        reasons = {row["skill"]: row["reason"] for row in result["skipped"] if row["provider"] == "agentsmd"}
        assert reasons == {"pre-release-audit": "malformed", "decision-log": "malformed"}


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

    def test_shared_doc_unlink_tolerates_file_vanishing_between_read_and_unlink(self, tmp_path, monkeypatch):
        # Round 35, Test-Adequacy front: the generic-provider branch's
        # missing_ok=True (above) has a red/green test; the shared-doc
        # branch's own, separate read-then-unlink sequence (installer.py's
        # `remove()`, the "still_referenced" block) never did, despite the
        # identical TOCTOU shape.
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        original_read_text = Path.read_text

        def read_then_vanish(self, *args, **kwargs):
            content = original_read_text(self, *args, **kwargs)
            if self == shared and shared.exists():
                shared.unlink()
            return content

        monkeypatch.setattr(Path, "read_text", read_then_vanish)

        result = installer.remove(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        removed_providers = {row["provider"] for row in result["removed"]}
        assert "copilot" in removed_providers
        assert not shared.exists()


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

    def test_time_scales_linearly_not_quadratically_with_tag_count(self, tmp_path):
        # Round 35, Test-Adequacy front: the absolute-threshold test above
        # only reliably catches a full revert to the old catastrophic-
        # backtracking regex -- a "mild" quadratic reintroduction built from
        # fast C-level primitives (str.find/str.count in a loop) measured
        # 0.14-0.78s at this same input size, comfortably under 3.0s despite
        # being genuinely O(n^2). A scaling/ratio test catches the
        # complexity CLASS regardless of the implementation's constant
        # factor: linear growth scales ~8x for an 8x input increase;
        # quadratic scales ~64x.
        def measure(target, n):
            target.mkdir()
            content = ("<!-- adrpy:skills:decision-log:start -->\n" + "x" * 200) * n
            (target / "AGENTS.md").write_text(content, encoding="utf-8")
            started = time.perf_counter()
            installer.list_installed(str(target), ["agentsmd"], ["decision-log"])
            return time.perf_counter() - started

        small = measure(tmp_path / "small", 500)
        large = measure(tmp_path / "large", 4000)  # 8x the tag count
        ratio = large / max(small, 1e-6)
        assert ratio < 20, (
            f"scaling ratio {ratio:.1f}x for an 8x input-size increase suggests super-linear behavior "
            f"(small={small:.4f}s, large={large:.4f}s)"
        )


class TestReadRetriesTransientPermissionError:
    """Round 35 resilience front: installer.py's own reads never used the
    project's shared read_with_permission_retry (core/io_retry.py), unlike
    every other reader (core/config.py, core/lock.py, core/lifecycle.py) --
    a single transient PermissionError (a Windows "pending delete" window
    under a concurrent reader) failed the whole install/remove/list call
    outright instead of being absorbed."""

    def test_install_absorbs_a_single_transient_permission_error_on_read(self, tmp_path, monkeypatch):
        installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        path = tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc"
        original_open = Path.open
        calls = {"count": 0}

        def flaky_open(self, *args, **kwargs):
            if self == path:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise PermissionError("transient contention")
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", flaky_open)

        result = installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert result["skipped"] == []
        assert calls["count"] >= 2


class TestWriteRetryVisibility:
    """Round 35 resilience front: a write that only succeeded after
    absorbing transient contention was silently discarded -- every core-CLI
    write site captures atomic_write_text's own attempt count and surfaces
    it via core.warnings.retry_warning; installer.py's 4 call sites didn't."""

    def test_install_reports_a_warning_after_absorbing_a_transient_write_retry(self, tmp_path, monkeypatch):
        def multi_attempt_write(path, content):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            return 3

        monkeypatch.setattr(installer, "atomic_write_text", multi_attempt_write)

        result = installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert any("3 attempts" in w for w in result["warnings"])


class TestSharedDocWrittenBeforeStubProviders:
    """Round 35 resilience front: needs_shared_doc used to be discovered as
    a side effect of the provider loop, and the shared doc was only written
    AFTER the whole loop finished -- reproduced: interrupting install()
    between two stub-mode providers left the first one's file referencing a
    doc/ai-skills/<name>.md that was never written, with list_installed()
    reporting a false drifted: false the whole time. Fixed by computing
    needs_shared_doc from the request alone (no I/O) and writing the shared
    doc before the provider loop starts."""

    def test_shared_doc_exists_before_any_stub_provider_is_written(self, tmp_path, monkeypatch):
        original_atomic_write_text = installer.atomic_write_text
        shared_doc_path = tmp_path / "doc" / "ai-skills" / "decision-log.md"
        stub_writes_saw_shared_doc_missing = []

        def spy(path, content):
            if path != shared_doc_path:
                stub_writes_saw_shared_doc_missing.append(not shared_doc_path.exists())
            return original_atomic_write_text(path, content)

        monkeypatch.setattr(installer, "atomic_write_text", spy)

        installer.install(str(tmp_path), ["copilot", "agentsmd"], ["decision-log"], "project", False)
        assert stub_writes_saw_shared_doc_missing == [False, False]


class TestSharedDocReportingAndBlocking:
    """Round 36 re-verification finding: two bugs in install() around the
    shared doc's own success/blocked status."""

    def test_shared_doc_write_appears_in_installed(self, tmp_path):
        # High: a successful shared-doc write never appeared anywhere in
        # the result, even in the plain happy path -- a caller checking
        # `installed` for confirmation of what was actually written on
        # disk would have missed it entirely.
        result = installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared_rows = [row for row in result["installed"] if row["provider"] == "shared-doc"]
        assert len(shared_rows) == 1
        assert shared_rows[0]["file"] == str(tmp_path / "doc" / "ai-skills" / "comment-audit.md")

    def test_blocked_shared_doc_prevents_stub_provider_from_writing_a_stale_reference(self, tmp_path):
        # High: a foreign/drifted shared doc, blocked without --force,
        # used to have no effect on whether a stub-mode provider's own
        # file still got written pointing at it -- reported as a clean
        # install success while referencing content that was never
        # actually verified or regenerated.
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.parent.mkdir(parents=True)
        shared.write_text("hand-written doc, no marker at all", encoding="utf-8")

        result = installer.install(str(tmp_path), ["agentsmd"], ["comment-audit"], "project", False)

        assert "agentsmd" not in {row["provider"] for row in result["installed"]}
        agentsmd_skip = next(row for row in result["skipped"] if row["provider"] == "agentsmd")
        assert agentsmd_skip["reason"] == "shared-doc-blocked"
        assert not (tmp_path / "AGENTS.md").exists()
        assert shared.read_text(encoding="utf-8") == "hand-written doc, no marker at all"

    def test_force_writes_both_the_shared_doc_and_the_stub_provider_it_blocked(self, tmp_path):
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        shared.parent.mkdir(parents=True)
        shared.write_text("hand-written doc, no marker at all", encoding="utf-8")

        result = installer.install(str(tmp_path), ["agentsmd"], ["comment-audit"], "project", True)

        assert "agentsmd" in {row["provider"] for row in result["installed"]}
        assert (tmp_path / "AGENTS.md").exists()
        assert "hand-written" not in shared.read_text(encoding="utf-8")


class TestWarningIdentityAndWording:
    """Round 36 re-verification finding: retry_warning's own message
    carries no file identity, ambiguous in install()/remove() specifically
    (the one place in the project that can write several files in one
    call); and --force's "overwritten" wording overstates what happens to
    a malformed agentsmd block's own orphaned body text."""

    def test_retry_warning_identifies_which_file_needed_retries(self, tmp_path, monkeypatch):
        def multi_attempt_write(path, content):
            from pathlib import Path as _Path

            _Path(path).parent.mkdir(parents=True, exist_ok=True)
            _Path(path).write_text(content, encoding="utf-8")
            return 3

        monkeypatch.setattr(installer, "atomic_write_text", multi_attempt_write)

        result = installer.install(str(tmp_path), ["cursor"], ["pre-release-audit"], "project", False)
        assert any(w.startswith("cursor/pre-release-audit: ") and "3 attempts" in w for w in result["warnings"])

    def test_force_over_malformed_block_does_not_claim_the_body_was_overwritten(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- adrpy:skills:pre-release-audit:start -->\nno matching end tag here\n",
            encoding="utf-8",
        )
        result = installer.install(str(tmp_path), ["agentsmd"], ["pre-release-audit"], "project", True)
        warning = next(w for w in result["warnings"] if "pre-release-audit" in w)
        assert "overwritten" not in warning
        assert "left in place" in warning


class TestReadTextTOCTOUCollapse:
    """Round 37, Class P2: the `path.exists()`-then-`_read_text(path)`
    pattern was repeated 9 times across this file; two of the nine
    (list_installed's own reads, and the shared-doc-removal check inside
    remove()) had no protection at all against the file vanishing in
    between, and could crash with a raw, uncaught FileNotFoundError --
    reachable even from `list` (read-only), and from `remove()` AFTER it
    had already committed a real deletion for an earlier (provider,
    skill) pair in the same call, silently discarding that success from
    the caller's view. Fixed by folding the existence check into
    `_read_text` itself (returns None on FileNotFoundError) and removing
    every separate `.exists()` guard, closing the whole class in one
    pass instead of patching the two flagged sites alone."""

    def test_read_text_returns_none_for_a_nonexistent_path(self, tmp_path):
        assert installer._read_text(tmp_path / "does-not-exist.md") is None

    def test_list_installed_tolerates_a_file_vanishing_exactly_at_the_read(self, tmp_path, monkeypatch):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        path = tmp_path / ".github" / "instructions" / "comment-audit.instructions.md"
        original_open = Path.open

        def vanish_then_raise(self, *args, **kwargs):
            if self == path:
                raise FileNotFoundError(2, "No such file or directory", str(self))
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", vanish_then_raise)

        rows = installer.list_installed(str(tmp_path), ["copilot"], ["comment-audit"])["skills"]
        assert rows[0]["installed"] is False
        assert rows[0]["drifted"] is None

    def test_remove_tolerates_shared_doc_vanishing_during_its_own_post_loop_check(self, tmp_path, monkeypatch):
        installer.install(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "comment-audit.md"
        original_open = Path.open

        def vanish_then_raise(self, *args, **kwargs):
            if self == shared:
                raise FileNotFoundError(2, "No such file or directory", str(self))
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", vanish_then_raise)

        result = installer.remove(str(tmp_path), ["copilot"], ["comment-audit"], "project", False)
        # copilot's own removal must have committed for real (and been
        # reported) despite the later shared-doc check hitting a vanished
        # file, instead of the whole call crashing after the fact.
        assert any(row["provider"] == "copilot" for row in result["removed"])


class TestReadTextSizeCap:
    """Round 37, Class P5: _read_text had no size cap -- a front measured
    an unbounded read of a planted 100MB file peaking process memory near
    200MB. Every other full-content reader in the project already caps
    (core/config.py's CONFIG_READ_MAX_BYTES, core/lock.py's own
    LOCK_READ_MAX_BYTES); this was the one that didn't."""

    def test_a_file_over_the_cap_raises_oserror_instead_of_loading_it_whole(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_READ_TEXT_MAX_BYTES", 100)
        oversized = tmp_path / "oversized.md"
        oversized.write_text("x" * 500, encoding="utf-8")

        with pytest.raises(OSError):
            installer._read_text(oversized)

    def test_a_file_at_or_under_the_cap_still_reads_normally(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_READ_TEXT_MAX_BYTES", 100)
        fine = tmp_path / "fine.md"
        fine.write_text("x" * 100, encoding="utf-8")

        assert installer._read_text(fine) == "x" * 100


class TestTargetValidation:
    """Round 37, Class P3: --provider/--skill both reject an unrecognized
    value via _expand(); --target never did -- a typo silently fell
    through to the 'project' branch instead of failing loudly."""

    def test_unknown_target_value_is_a_usage_error_on_install(self, tmp_path):
        with pytest.raises(UsageError):
            installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "bogus", False)
        assert list(tmp_path.rglob("*")) == []

    def test_unknown_target_value_is_a_usage_error_on_remove(self, tmp_path):
        with pytest.raises(UsageError):
            installer.remove(str(tmp_path), ["claude"], ["pre-release-audit"], "bogus", False)

    def test_project_and_global_still_work(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "project", False)
        installer.install(str(tmp_path), ["claude"], ["pre-release-audit"], "global", False)
        assert (tmp_path / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").exists()
        assert (home / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").exists()
