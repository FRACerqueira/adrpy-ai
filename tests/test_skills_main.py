import json
from pathlib import Path

from adrpy.skills.__main__ import main
from adrpy.skills.providers import PROVIDERS
from adrpy.skills.resources import SKILL_NAMES

import pytest


def _run(argv, capsys):
    exit_code = main(argv)
    out = json.loads(capsys.readouterr().out)
    return exit_code, out


class TestCliDispatch:
    def test_install_via_cli(self, tmp_path, capsys):
        exit_code, out = _run(
            ["install", "--path", str(tmp_path), "--skill", "pre-release-audit", "--provider", "cursor"], capsys
        )
        assert exit_code == 0
        assert out["success"] is True
        assert len(out["data"]["installed"]) == 1
        assert (tmp_path / ".cursor" / "rules" / "pre-release-audit.mdc").exists()

    def test_list_via_cli_defaults_to_all(self, tmp_path, capsys):
        main(["install", "--path", str(tmp_path), "--skill", "comment-audit", "--provider", "cursor"])
        capsys.readouterr()
        exit_code, out = _run(["list", "--path", str(tmp_path)], capsys)
        assert exit_code == 0
        # Exact count, not just "> 1" -- every provider x every skill, with
        # claude contributing an extra row for its own global scope (every
        # other provider is project-scope only), plus one "shared-doc" row
        # per skill since "all" providers includes at least one stub-mode
        # provider (copilot, agentsmd) -- so a row silently going missing
        # wouldn't slip by.
        rows_per_skill = sum(2 if spec["global_path"] is not None else 1 for spec in PROVIDERS.values()) + 1
        assert len(out["data"]["skills"]) == len(SKILL_NAMES) * rows_per_skill

    def test_install_via_short_aliases(self, tmp_path, capsys):
        exit_code, out = _run(
            ["install", "-p", "cursor", "-s", "pre-release-audit", "--path", str(tmp_path)], capsys
        )
        assert exit_code == 0
        assert len(out["data"]["installed"]) == 1

    def test_remove_via_cli(self, tmp_path, capsys):
        main(["install", "--path", str(tmp_path), "--skill", "pre-release-audit", "--provider", "cursor"])
        capsys.readouterr()
        exit_code, out = _run(
            ["remove", "--path", str(tmp_path), "--skill", "pre-release-audit", "--provider", "cursor"], capsys
        )
        assert exit_code == 0
        assert len(out["data"]["removed"]) == 1

    def test_unknown_verb_is_a_usage_error(self, capsys):
        exit_code, out = _run(["frobnicate"], capsys)
        assert exit_code == 2
        assert out == {"success": False, "code": "unknown-command"}

    def test_unknown_flag_is_a_usage_error(self, tmp_path, capsys):
        exit_code, out = _run(["install", "--bogus", "x"], capsys)
        assert exit_code == 2
        assert out["code"] == "usage-error"

    def test_global_scope_on_unsupported_provider_is_a_usage_error(self, tmp_path, capsys):
        exit_code, out = _run(
            ["install", "--path", str(tmp_path), "--provider", "cursor", "--target", "global"], capsys
        )
        assert exit_code == 2
        assert out["code"] == "usage-error"
        assert list(tmp_path.rglob("*")) == []

    def test_help_flag_lists_every_command(self, capsys):
        exit_code, out = _run(["--help"], capsys)
        assert exit_code == 0
        assert {c["name"] for c in out["data"]["commands"]} == {"help", "install", "remove", "list"}

    def test_no_args_lists_every_command(self, capsys):
        exit_code, out = _run([], capsys)
        assert exit_code == 0
        assert {c["name"] for c in out["data"]["commands"]} == {"help", "install", "remove", "list"}

    def test_version_flag_prints_and_exits_zero(self, capsys):
        exit_code = main(["--version"])
        out = capsys.readouterr().out
        assert exit_code == 0
        assert out.startswith("adrpy-skills ")

    def test_short_version_flag_also_works(self, capsys):
        exit_code = main(["-v"])
        out = capsys.readouterr().out
        assert exit_code == 0
        assert out.startswith("adrpy-skills ")

    def test_remove_via_short_aliases(self, tmp_path, capsys):
        # Round 35, Test-Adequacy front: -p/-s were exercised via the real
        # CLI (test_install_via_short_aliases above), but -t and -f never
        # were -- describe()'s own alias metadata was checked, and so was
        # parse_flags' aliases= dict via AST inspection, but neither of
        # those actually invokes the CLI with -t/-f, so either could drop
        # from the real aliases={...} kwarg with every existing test still
        # green.
        main(["install", "--path", str(tmp_path), "-s", "pre-release-audit", "-p", "cursor"])
        capsys.readouterr()
        exit_code, out = _run(["remove", "--path", str(tmp_path), "-s", "pre-release-audit", "-p", "cursor", "-f"], capsys)
        assert exit_code == 0
        assert len(out["data"]["removed"]) == 1

    def test_target_global_via_short_alias(self, tmp_path, capsys, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        exit_code, out = _run(["install", "-p", "claude", "-s", "pre-release-audit", "-t", "global"], capsys)
        assert exit_code == 0
        assert len(out["data"]["installed"]) == 1
        assert (home / ".claude" / "skills" / "pre-release-audit" / "SKILL.md").exists()

    def test_provider_comma_with_nothing_after_is_a_usage_error_via_cli(self, tmp_path, capsys):
        # Round 35, Test-Adequacy front: the empty-after-split rejection was
        # only ever tested by calling installer.install([], ...) directly,
        # bypassing commands/install.py's own _split() entirely -- a
        # regression there (e.g. `... or ["all"]`, silently widening the
        # blast radius to "all providers" on a mistyped flag) would pass
        # every existing test.
        exit_code, out = _run(["install", "--path", str(tmp_path), "--provider", ","], capsys)
        assert exit_code == 2
        assert out["code"] == "usage-error"
        assert list(tmp_path.rglob("*")) == []

    def test_short_help_flag_also_works(self, capsys):
        exit_code, out = _run(["-h"], capsys)
        assert exit_code == 0
        assert {c["name"] for c in out["data"]["commands"]} == {"help", "install", "remove", "list"}

    def test_unexpected_exception_is_reported_as_internal_error_not_a_raw_traceback(self, tmp_path, capsys, monkeypatch):
        # Round 32, Class F: an exception outside UsageError/OSError (e.g. a
        # UnicodeDecodeError from a pre-existing non-UTF-8 file) must still
        # come back as a JSON envelope, never an uncaught traceback with
        # empty stdout.
        import adrpy.skills.installer as installer_module

        def boom(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(installer_module, "install", boom)
        exit_code, out = _run(["install", "--path", str(tmp_path)], capsys)
        assert exit_code != 0
        assert out["success"] is False
        assert out["code"] == "internal-error"

    def test_keyboard_interrupt_still_emits_json_on_stdout(self, tmp_path, capsys, monkeypatch):
        # Round 37, Class P1: adrpy/__main__.py already catches
        # KeyboardInterrupt (a BaseException, not an Exception -- the
        # generic except Exception above never sees it); this sibling
        # entry point never got the same fix until now.
        import adrpy.skills.installer as installer_module

        def boom(*args, **kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr(installer_module, "install", boom)
        exit_code, out = _run(["install", "--path", str(tmp_path)], capsys)
        assert exit_code != 0
        assert out["success"] is False
        assert out["code"] == "interrupted"


class TestPartialEffectsSurviveAFailure:
    """A failure partway through install/remove must still report what
    that same call already wrote or deleted, and the warnings it already
    collected -- the caller can't otherwise tell what changed on disk."""

    @staticmethod
    def _isolate_home(tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

    @staticmethod
    def _fail_on_write(monkeypatch, failing_call, error):
        from adrpy.skills import installer as installer_module

        real_write = installer_module.atomic_write_text
        calls = {"n": 0}

        def write(path, content):
            calls["n"] += 1
            if calls["n"] == failing_call:
                raise error
            return real_write(path, content)

        monkeypatch.setattr(installer_module, "atomic_write_text", write)

    def test_an_io_error_midway_through_install_reports_what_was_already_written(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        self._fail_on_write(monkeypatch, 3, OSError(28, "No space left on device"))

        exit_code, out = _run(
            ["install", "--path", str(tmp_path), "--provider", "claude,cursor", "--skill", "comment-audit,decision-log"],
            capsys,
        )

        assert exit_code != 0
        assert out["code"] == "io-error"
        written = [(row["provider"], row["skill"]) for row in out["data"]["installed"]]
        assert written == [("claude", "comment-audit"), ("cursor", "comment-audit")]
        assert out["warnings"] == []

    def test_an_interrupt_midway_through_install_reports_what_was_already_written(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        self._fail_on_write(monkeypatch, 2, KeyboardInterrupt())

        exit_code, out = _run(
            ["install", "--path", str(tmp_path), "--provider", "claude,cursor", "--skill", "comment-audit"], capsys
        )

        assert out["code"] == "interrupted"
        assert [row["provider"] for row in out["data"]["installed"]] == ["claude"]

    def test_a_non_utf8_agentsmd_is_an_io_error_naming_the_file_not_an_internal_error(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        (tmp_path / "AGENTS.md").write_bytes("# Notas do projeto\n".encode("utf-16"))

        main(["list", "--path", str(tmp_path), "--provider", "agentsmd"])
        captured = capsys.readouterr()

        assert json.loads(captured.out)["code"] == "io-error"
        assert "AGENTS.md" in captured.err and "UTF-8" in captured.err

    def test_remove_reports_deletions_made_before_an_unreadable_agentsmd(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        main(["install", "--path", str(tmp_path), "--provider", "claude", "--skill", "comment-audit"])
        capsys.readouterr()
        (tmp_path / "AGENTS.md").write_bytes("# Notas do projeto\n".encode("utf-16"))

        exit_code, out = _run(
            ["remove", "--path", str(tmp_path), "--provider", "claude,agentsmd", "--skill", "comment-audit"], capsys
        )

        assert out["code"] == "io-error"
        assert [row["provider"] for row in out["data"]["removed"]] == ["claude"]
        assert not (tmp_path / ".claude" / "skills" / "comment-audit" / "SKILL.md").exists()


class TestCliErgonomics:
    @staticmethod
    def _isolate_home(tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        return home

    def _run_err(self, argv, capsys):
        exit_code = main(argv)
        captured = capsys.readouterr()
        return exit_code, json.loads(captured.out), captured.err

    def test_target_tolerates_surrounding_spaces_like_provider_and_skill(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        exit_code, out = _run(
            ["install", "--path", str(tmp_path), "-p", " cursor", "-s", " comment-audit", "-t", " project"], capsys
        )
        assert exit_code == 0 and out["success"] is True

    def test_unknown_values_name_their_flag_and_are_reported_together(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        _, out, err = self._run_err(["install", "--path", str(tmp_path), "-p", "claude,bogus", "-s", "nope"], capsys)
        assert out["code"] == "usage-error"
        assert "--provider" in err and "bogus" in err and "--skill" in err and "nope" in err

    def test_help_for_an_unknown_command_is_unknown_command_like_adrpy(self, capsys):
        exit_code, out = _run(["help", "nosuch"], capsys)
        assert out["code"] == "unknown-command"

    @pytest.mark.parametrize("verb", ["install", "remove", "list"])
    def test_a_missing_path_is_refused_not_created(self, tmp_path, monkeypatch, capsys, verb):
        self._isolate_home(tmp_path, monkeypatch)
        missing = tmp_path / "does" / "not" / "exist"
        exit_code, out = _run([verb, "--path", str(missing), "-p", "cursor", "-s", "comment-audit"], capsys)
        assert out["code"] == "target-directory-not-found"
        assert not missing.exists()

    def test_target_global_with_no_provider_defaults_to_the_global_capable_ones(self, tmp_path, monkeypatch, capsys):
        home = self._isolate_home(tmp_path, monkeypatch)
        exit_code, out = _run(["install", "-t", "global", "-s", "comment-audit"], capsys)
        assert exit_code == 0
        assert [row["provider"] for row in out["data"]["installed"]] == ["claude"]
        assert (home / ".claude" / "skills" / "comment-audit" / "SKILL.md").exists()

    def test_an_explicit_all_with_target_global_suggests_the_provider_to_use(self, tmp_path, monkeypatch, capsys):
        self._isolate_home(tmp_path, monkeypatch)
        _, out, err = self._run_err(["install", "-t", "global", "-p", "all", "-s", "comment-audit"], capsys)
        assert out["code"] == "usage-error"
        assert "--provider claude" in err
