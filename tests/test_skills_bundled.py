"""The bundled skills' own content: the `adrpy` skill (installed, listed,
drift-checked and removed like the others, for every provider) and the
decision-log write gate's explicit-request clause."""

from pathlib import Path

import pytest

from adrpy.core.errors import UsageError
from adrpy.core.hashing import check_drift
from adrpy.core.registry import COMMANDS
from adrpy.skills import installer, resources
from adrpy.skills.providers import ALL_PROVIDERS

_FILE_PATHS = {
    "claude": ".claude/skills/adrpy/SKILL.md",
    "cursor": ".cursor/rules/adrpy.mdc",
    "copilot": ".github/instructions/adrpy.instructions.md",
}


def _agents_block(tmp_path):
    return installer._agentsmd_extract_inner((tmp_path / "AGENTS.md").read_text(encoding="utf-8"), "adrpy")


class TestAdrpySkillIsBundled:
    def test_it_is_a_shipped_skill_with_its_own_meta(self):
        assert "adrpy" in resources.SKILL_NAMES
        assert resources.load_meta("adrpy")["name"] == "adrpy"

    def test_its_trigger_names_the_config_file(self):
        assert "adr-config.adrplus" in resources.load_meta("adrpy")["description"]
        assert "adr-config.adrplus" in resources.load_full_content("adrpy")

    def test_it_maps_every_adrpy_command(self):
        # Drift guard: a command added to adrpy without a line in the skill fails here.
        content = resources.load_full_content("adrpy")
        missing = [name for name in COMMANDS if f"`adrpy {name}" not in content]
        assert missing == []

    def test_it_states_the_rules_an_agent_needs(self):
        content = resources.load_full_content("adrpy")
        for needle in (
            "adrpy check --path .",
            "`hint`",
            "<sep><sep>NNN",
            "adrpy supersede --file",
            "--title",
            "one command at a time",
            "adrpy <command> --help",
            "adrpy help <command>",
        ):
            assert needle in content, needle

    @pytest.mark.parametrize("skill", resources.SKILL_NAMES)
    def test_every_description_is_plain_yaml_in_the_frontmatter(self, skill):
        # claude/cursor put the description in YAML frontmatter unquoted:
        # ": " or " #" would break it, and the provider would not load the skill.
        description = resources.load_meta(skill)["description"]
        assert ": " not in description and " #" not in description and "\n" not in description


class TestAdrpySkillInstall:
    @pytest.mark.parametrize("provider", ["claude", "cursor", "copilot"])
    def test_installs_listed_clean_and_removed(self, tmp_path, provider):
        result = installer.install(str(tmp_path), [provider], ["adrpy"], "project", False)
        assert result["skipped"] == []
        path = tmp_path / _FILE_PATHS[provider]
        assert check_drift(path.read_text(encoding="utf-8")) == "clean"

        rows = installer.list_installed(str(tmp_path), [provider], ["adrpy"])["skills"]
        own = [row for row in rows if row["provider"] == provider and row["scope"] == "project"]
        assert own[0]["installed"] is True and own[0]["drifted"] is False

        installer.remove(str(tmp_path), [provider], ["adrpy"], "project", False)
        assert not path.exists()

    def test_full_mode_providers_get_the_whole_skill_inline(self, tmp_path):
        installer.install(str(tmp_path), ["claude", "cursor"], ["adrpy"], "project", False)
        for provider in ("claude", "cursor"):
            assert "# Working with adrpy" in (tmp_path / _FILE_PATHS[provider]).read_text(encoding="utf-8")
        assert (tmp_path / _FILE_PATHS["claude"]).read_text(encoding="utf-8").startswith("---\nname: adrpy\n")

    def test_stub_mode_providers_point_at_the_shared_doc(self, tmp_path):
        installer.install(str(tmp_path), ["copilot", "agentsmd"], ["adrpy"], "project", False)
        shared = tmp_path / "doc" / "ai-skills" / "adrpy.md"
        assert "# Working with adrpy" in shared.read_text(encoding="utf-8")
        assert "doc/ai-skills/adrpy.md" in (tmp_path / _FILE_PATHS["copilot"]).read_text(encoding="utf-8")
        assert "doc/ai-skills/adrpy.md" in _agents_block(tmp_path)

        installer.remove(str(tmp_path), ["copilot", "agentsmd"], ["adrpy"], "project", False)
        assert not shared.exists()
        assert "adrpy:skills:adrpy" not in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize("provider", ["claude", "cursor", "copilot"])
    def test_a_hand_edit_is_drifted_and_kept(self, tmp_path, provider):
        installer.install(str(tmp_path), [provider], ["adrpy"], "project", False)
        path = tmp_path / _FILE_PATHS[provider]
        path.write_text(path.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.install(str(tmp_path), [provider], ["adrpy"], "project", False)
        assert [(row["provider"], row["reason"]) for row in result["skipped"]] == [(provider, "drifted")]
        assert "HAND EDITED" in path.read_text(encoding="utf-8")
        rows = installer.list_installed(str(tmp_path), [provider], ["adrpy"])["skills"]
        assert [row["drifted"] for row in rows if row["provider"] == provider and row["scope"] == "project"] == [True]

    def test_a_hand_edited_agentsmd_block_is_drifted_and_kept(self, tmp_path):
        installer.install(str(tmp_path), ["agentsmd"], ["adrpy"], "project", False)
        agents_md = tmp_path / "AGENTS.md"
        text = agents_md.read_text(encoding="utf-8")
        agents_md.write_text(text.replace("### adrpy", "### adrpy (EDITED)"), encoding="utf-8")

        result = installer.install(str(tmp_path), ["agentsmd"], ["adrpy"], "project", False)
        assert [(row["provider"], row["reason"]) for row in result["skipped"]] == [("agentsmd", "drifted")]
        assert "### adrpy (EDITED)" in agents_md.read_text(encoding="utf-8")

    def test_global_claude_install_lands_under_the_patched_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        result = installer.install(str(tmp_path / "repo"), ["claude"], ["adrpy"], "global", False)
        assert result["skipped"] == []
        assert check_drift((home / ".claude" / "skills" / "adrpy" / "SKILL.md").read_text(encoding="utf-8")) == "clean"
        installer.remove(str(tmp_path / "repo"), ["claude"], ["adrpy"], "global", False)
        assert not (home / ".claude" / "skills" / "adrpy" / "SKILL.md").exists()

    def test_all_skills_install_includes_adrpy_for_every_provider(self, tmp_path):
        result = installer.install(str(tmp_path), ["all"], ["all"], "project", False)
        providers = {row["provider"] for row in result["installed"] if row["skill"] == "adrpy"}
        assert providers == set(ALL_PROVIDERS) | {"shared-doc"}


class TestDecisionLogGateHonorsAnExplicitRequest:
    CLAUSE = (
        "If the user's own message explicitly asks to record this specific decision or "
        "entry, that request is the separate approval for that one write: fill only what "
        "they gave, ask only for required fields that are missing (for `adrpy log`: e.g. "
        "`--front`/`--resolution` for `audit-finding`), then report exactly what was written."
    )

    def test_the_gate_carries_the_clause(self):
        content = " ".join(resources.load_full_content("decision-log").split())
        assert self.CLAUSE in content

    def test_the_gate_points_writes_to_the_adrpy_commands(self):
        content = " ".join(resources.load_full_content("decision-log").split())
        assert "never a hand-written file" in content
        assert "`adrpy log` for a decision-log entry" in content

    def test_the_description_no_longer_demands_a_confirmation_for_an_explicit_request(self):
        description = resources.load_meta("decision-log")["description"]
        assert "unless the user's own message explicitly asks to record that specific entry" in description


def _old_comment_audit_install(tmp_path, monkeypatch, providers=("all",), scope="project"):
    """What an older adrpy-skills, which still shipped comment-audit, left on disk."""
    shipped = resources.SKILL_NAMES
    real_meta, real_content = resources.load_meta, resources.load_full_content
    with monkeypatch.context() as patch:
        patch.setattr(resources, "SKILL_NAMES", shipped + ("comment-audit",))
        patch.setattr(
            resources,
            "load_meta",
            lambda name: {"name": name, "description": "Old comment audit."} if name == "comment-audit" else real_meta(name),
        )
        patch.setattr(
            resources,
            "load_full_content",
            lambda name: "# Comment audit\n\nOld body.\n" if name == "comment-audit" else real_content(name),
        )
        result = installer.install(str(tmp_path), list(providers), ["comment-audit"], scope, False)
    assert result["skipped"] == []
    return result


class TestCommentAuditIsRetired:
    def test_it_is_no_longer_shipped(self):
        assert "comment-audit" not in resources.SKILL_NAMES
        assert not (resources.resources.files("adrpy.resources.skills") / "comment-audit").is_dir()

    def test_install_refuses_it(self, tmp_path):
        with pytest.raises(UsageError):
            installer.install(str(tmp_path), ["claude"], ["comment-audit"], "project", False)

    def test_install_all_does_not_write_it(self, tmp_path):
        installer.install(str(tmp_path), ["all"], ["all"], "project", False)
        assert list(tmp_path.rglob("*comment-audit*")) == []
        assert "comment-audit" not in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    def test_remove_all_cleans_up_an_older_install(self, tmp_path, monkeypatch):
        _old_comment_audit_install(tmp_path, monkeypatch)
        assert list(tmp_path.rglob("*comment-audit*"))

        result = installer.remove(str(tmp_path), ["all"], ["all"], "project", False)
        removed = {(row["provider"], row["skill"]) for row in result["removed"]}
        assert {(p, "comment-audit") for p in (*ALL_PROVIDERS, "shared-doc")} <= removed
        assert [p for p in tmp_path.rglob("*comment-audit*") if p.is_file()] == []
        assert "adrpy:skills:comment-audit" not in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    def test_remove_by_name_cleans_up_an_older_global_install(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        _old_comment_audit_install(tmp_path, monkeypatch, providers=("claude",), scope="global")
        skill_file = home / ".claude" / "skills" / "comment-audit" / "SKILL.md"
        assert skill_file.exists()

        installer.remove(str(tmp_path), ["claude"], ["comment-audit"], "global", False)
        assert not skill_file.exists()

    def test_remove_keeps_a_hand_edited_older_install(self, tmp_path, monkeypatch):
        _old_comment_audit_install(tmp_path, monkeypatch, providers=("claude",))
        path = tmp_path / ".claude" / "skills" / "comment-audit" / "SKILL.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nHAND EDITED\n", encoding="utf-8")

        result = installer.remove(str(tmp_path), ["claude"], ["all"], "project", False)
        assert [(row["skill"], row["reason"]) for row in result["skipped"]] == [("comment-audit", "drifted")]
        assert path.exists()

    def test_list_shows_an_older_install_but_not_an_absent_one(self, tmp_path, monkeypatch):
        rows = installer.list_installed(str(tmp_path), ["all"], ["all"])["skills"]
        assert "comment-audit" not in {row["skill"] for row in rows}

        _old_comment_audit_install(tmp_path, monkeypatch, providers=("cursor",))
        rows = installer.list_installed(str(tmp_path), ["all"], ["all"])["skills"]
        retired = [(row["provider"], row["installed"], row["drifted"]) for row in rows if row["skill"] == "comment-audit"]
        assert retired == [("cursor", True, False)]

    def test_list_by_name_reports_every_row(self, tmp_path):
        rows = installer.list_installed(str(tmp_path), ["cursor"], ["comment-audit"])["skills"]
        assert [(row["provider"], row["installed"]) for row in rows] == [("cursor", False)]

    def test_no_unqualified_ask_every_time_remains(self):
        # Every "still needs its own ask" in the shipped text names the explicit-request exception.
        content = " ".join(resources.load_full_content("decision-log").split())
        for position in [i for i in range(len(content)) if content.startswith("still needs its own ask", i)]:
            assert "explicit request" in content[position : position + 120], content[position : position + 120]
