import json

from adrpy.skills.__main__ import main


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
        assert len(out["data"]["skills"]) > 1  # every provider x every skill

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

    def test_help_flag_does_not_error(self, capsys):
        exit_code = main(["--help"])
        assert exit_code == 0

    def test_no_args_does_not_error(self, capsys):
        exit_code = main([])
        assert exit_code == 0
