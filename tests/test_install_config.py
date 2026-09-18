import json
import os
from pathlib import Path

import pytest

from adrpy.core.errors import CommandError
from adrpy.core.install_config import read_install_config_text, resolve_install_config_path

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _valid_config_dict():
    return {
        "folderadr": "doc/adr",
        "migrationpattern": "",
        "template": "template content",
        "prefix": "ADR",
        "lenseq": 3,
        "lenversion": 2,
        "lenrevision": 0,
        "separator": "-",
        "casetransform": "KebabCase",
        "statusnew": "Proposed",
        "statusacc": "Accepted",
        "statusrej": "Rejected",
        "statussup": "Superseded",
        "headerdisclaimer": "Do not remove this comment, lines and table",
        "headertitlefile": "File title md",
        "headerversion": "Version",
        "headerrevision": "Revision",
        "headerscope": "Scope",
        "headerdomain": "Domain",
        "headertitlestatuscreated": "Created",
        "headertitlestatuschanged": "Changed",
        "headertitlestatussuperseded": "Superseded",
        "headertablefields": "Fields",
        "headertablevalues": "Values",
        "headermigrated": "Migrated",
        "activeplugins": [],
        "disableplugins": False,
    }


# --- resolve_install_config_path ---------------------------------------


_POSIX_SKIP_REASON = (
    "POSIX-only path convention -- pathlib cannot construct a PosixPath on a non-POSIX host "
    "(a deliberate Python 3.12 safety guard baked in at class-definition time, so monkeypatching "
    "os.name at test time does not change it); this branch can only run on a real POSIX host."
)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only path convention.")
def test_windows_path_uses_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")

    path = resolve_install_config_path()

    assert path == Path(r"C:\Users\someone\AppData\Roaming") / "adrpy" / "install-config.json"


@pytest.mark.skipif(os.name != "nt", reason="Windows-only path convention.")
def test_windows_path_falls_back_to_home_when_appdata_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    path = resolve_install_config_path()

    assert path == tmp_path / "AppData" / "Roaming" / "adrpy" / "install-config.json"


@pytest.mark.skipif(os.name != "posix", reason=_POSIX_SKIP_REASON)
def test_posix_path_uses_xdg_config_home(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/someone/.config")

    path = resolve_install_config_path()

    assert path == Path("/home/someone/.config") / "adrpy" / "install-config.json"


@pytest.mark.skipif(os.name != "posix", reason=_POSIX_SKIP_REASON)
def test_posix_path_falls_back_to_dot_config_when_xdg_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    path = resolve_install_config_path()

    assert path == tmp_path / ".config" / "adrpy" / "install-config.json"


# --- read_install_config_text -------------------------------------------


def test_returns_none_when_file_does_not_exist(tmp_path):
    missing = tmp_path / "install-config.json"

    assert read_install_config_text(missing) is None


def test_returns_raw_text_when_file_is_valid(tmp_path):
    target = tmp_path / "install-config.json"
    text = Path(FIXTURE_PATH).read_text(encoding="utf-8")
    target.write_text(text, encoding="utf-8")

    result = read_install_config_text(target)

    assert result == text


def test_raises_when_file_content_fails_schema_validation(tmp_path):
    data = _valid_config_dict()
    del data["lenseq"]
    target = tmp_path / "install-config.json"
    target.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        read_install_config_text(target)

    assert excinfo.value.code == "config-missing-field"


def test_default_path_used_when_none_given(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "adrpy.core.install_config.resolve_install_config_path", lambda: tmp_path / "install-config.json"
    )

    assert read_install_config_text() is None
