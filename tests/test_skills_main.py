import json

from adrpy.skills.__main__ import main
from adrpy.skills.providers import PROVIDERS
from adrpy.skills.resources import SKILL_NAMES


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
        # other provider is project-scope only) -- so a row silently going
        # missing wouldn't slip by.
        rows_per_skill = sum(2 if spec["global_path"] is not None else 1 for spec in PROVIDERS.values())
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
