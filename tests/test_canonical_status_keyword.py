"""Usability audit M4: every status-mutating command returned the
REPOSITORY'S OWN CONFIGURED LABEL (config.statusnew/statusacc/...) as
"status" in its JSON result, while `explore` -- reporting on the exact
same file -- always returns the canonical internal keyword
(header.status_create, "Proposed"/"Accepted"/"Rejected"/"Superseded").
The two coincide in every other test only because the default config
happens to set each label equal to its own canonical keyword; a
repository that customizes labels (which `config` allows with no
validation against anything) makes the two commands describe the same
decision with two different words, breaking an agent's ability to
correlate a mutation's own result with a later `explore` call."""

import json

from adrpy.cli import approve, explore, init, new, reject, revise, supersede, undo, version

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _custom_labels_config():
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["statusnew"] = "Rascunho"
    data["statusacc"] = "Aceito"
    data["statusrej"] = "Rejeitado"
    data["statussup"] = "Substituido"
    data["migrationpattern"] = ""
    data["lenrevision"] = 2
    return data


def _init_repo_with_custom_labels(tmp_path):
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_custom_labels_config()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--file", str(config_file)])
    return tmp_path


def _canonical_status(tmp_path, filename):
    entry = next(e for e in explore.run(["--path", str(tmp_path)])["decisions"] if e["filename"] == filename)
    return entry["header"]["status_create"], entry["header"]["status_update"], entry["header"]["status_change"]


def test_new_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)

    result = new.run(["--path", str(tmp_path), "--title", "Some decision"])

    assert result["status"] == "Proposed"


def test_approve_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Some decision"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-some-decision.md"

    result = approve.run(["--file", str(adr_path)])

    assert result["status"] == "Accepted"


def test_reject_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Some decision"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-some-decision.md"

    result = reject.run(["--file", str(adr_path)])

    assert result["status"] == "Rejected"


def test_undo_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Some decision"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-some-decision.md"
    approve.run(["--file", str(adr_path)])

    result = undo.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"


def test_supersede_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Some decision"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-some-decision.md"
    approve.run(["--file", str(adr_path)])

    result = supersede.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"


def test_version_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Some decision"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-some-decision.md"
    approve.run(["--file", str(adr_path)])

    result = version.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"


def test_revise_returns_the_canonical_keyword_not_the_configured_label(tmp_path):
    _init_repo_with_custom_labels(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Some decision"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-some-decision.md"
    approve.run(["--file", str(adr_path)])

    result = revise.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"
