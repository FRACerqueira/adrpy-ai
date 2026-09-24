import json
import os
import subprocess
import sys
from pathlib import Path

from adrpy.cli import init, new
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError

import pytest


def _default_config_text():
    from importlib import resources

    return resources.files("adrpy.resources").joinpath("default_repo_config.json").read_text(encoding="utf-8")


def test_init_fresh_repo_writes_default_config_and_creates_folder(tmp_path):
    result = init.run(["--path", str(tmp_path)])

    config_path = tmp_path / "adr-config.adrplus"
    assert config_path.read_text(encoding="utf-8") == _default_config_text()
    assert (tmp_path / "doc" / "adr").is_dir()
    assert result["created"] == [str(config_path), str(tmp_path / "doc" / "adr")]
    # No --seed, no --language, no install-level config on this machine
    # (the autouse fixture forces that) -- the one branch that seeded
    # from the built-in default with no informed source at all, so the
    # advisory warning recommending `installconfig` must be present.
    assert any("adrpy installconfig" in w for w in result["warnings"])


def test_init_does_not_recommend_installconfig_when_seed_is_given(tmp_path, tmp_path_factory):
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "seed.json"
    seed_file.write_text(_default_config_text(), encoding="utf-8")

    result = init.run(["--path", str(tmp_path), "--seed", str(seed_file)])

    assert not any("installconfig" in w for w in result["warnings"])


def test_init_does_not_recommend_installconfig_when_language_is_given(tmp_path):
    result = init.run(["--path", str(tmp_path), "--language", "pt-br"])

    assert not any("installconfig" in w for w in result["warnings"])


def test_init_does_not_recommend_installconfig_when_install_level_config_exists(tmp_path, monkeypatch):
    install_text = (Path("tests") / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8")
    monkeypatch.setattr(init, "read_install_config_text", lambda: install_text)

    result = init.run(["--path", str(tmp_path)])

    assert not any("installconfig" in w for w in result["warnings"])


def test_init_does_not_fail_when_a_concurrent_process_creates_the_decisions_folder_first(tmp_path, monkeypatch):
    """Verified live: this escapes as a clean `io-error`, not a generic
    `internal-error`, since FileExistsError is an OSError subclass
    __main__.py already catches. Distinct from the
    already-accepted config-already-exists race (doc/adr/ADR001V01-...'s
    own addendum): that race has genuinely conflicting content between
    two calls; this one doesn't -- both processes want the exact same
    end state (the folder exists), so there's nothing to lose by closing
    it outright, unlike init's other race."""
    real_mkdir = init.Path.mkdir
    triggered = {"done": False}

    def racing_mkdir(self, *args, **kwargs):
        if not triggered["done"] and self.name == "adr":
            triggered["done"] = True
            # Simulates a concurrent process creating the SAME directory
            # first, exactly between init's own is_dir()==False check and
            # this mkdir() call.
            real_mkdir(self, parents=True)
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(init.Path, "mkdir", racing_mkdir)

    result = init.run(["--path", str(tmp_path)])

    # No exception -- the race is closed, not just reported better. Both
    # processes wanted the exact same end state, so who structurally won
    # the mkdir() syscall doesn't matter; `created` still names the
    # folder, since this call's own is_dir() check (necessarily taken
    # before the race is even injected) legitimately observed it as
    # missing at that point -- a harmless reporting quirk, not a bug.
    assert (tmp_path / "doc" / "adr").is_dir()
    assert result["created"] == [str(tmp_path / "adr-config.adrplus"), str(tmp_path / "doc" / "adr")]


def test_init_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage."""
    real_atomic_write_text = init.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(init, "atomic_write_text", flaky_atomic_write_text)

    result = init.run(["--path", str(tmp_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_init_seed_rejects_a_folderlog_change_when_entries_already_exist(tmp_path):
    """ADR007V01: the folderlog counterpart to
    test_init_seed_rejects_a_folderadr_change_when_decisions_already_exist
    -- --seed changing folderlog on an already-existing repository can
    orphan existing decision-log entries the same way."""
    from adrpy.cli import log

    init.run(["--path", str(tmp_path)])
    log.run(
        ["--path", str(tmp_path), "--classification", "scope-note", "--scope", "test", "--slug", "x",
         "--summary", "s", "--body", "b"]
    )

    seed = json.loads(init.default_repo_config_text())
    seed["folderlog"] = "other-log"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "folderlog-change-blocked-by-existing-entries"
    on_disk = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert on_disk["folderlog"] == "doc/decision-log"


def test_init_seed_rejects_a_folderadr_change_when_decisions_already_exist(tmp_path):
    """Same class as config.py's own --folderadr guard -- --seed changing
    folderadr on an already-existing repository can orphan existing
    decisions exactly the same way. Distinct from config-already-exists
    (which --seed is meant to bypass): this is about the FOLDER, not the
    config file's own existence."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    seed = json.loads(init.default_repo_config_text())
    seed["folderadr"] = "decisions"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "folderadr-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"folderadr": "doc/adr", "existing_decisions": 1}
    # Nothing was written -- the original config survives untouched.
    on_disk = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert on_disk["folderadr"] == "doc/adr"


def test_init_seed_folderadr_change_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Folderadr-change-scan-
    incomplete was only ever tested at the core/lifecycle level, never
    through this real CLI command (init's own --seed path shares the
    same guard as config's own --folderadr)."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    seed = json.loads(init.default_repo_config_text())
    seed["folderadr"] = "decisions"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "folderadr-change-scan-incomplete"
    on_disk = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert on_disk["folderadr"] == "doc/adr"  # nothing was written


def test_init_seed_rejects_a_folderadr_change_that_would_adopt_an_unrelated_file(tmp_path):
    """Same class as config.py's own --folderadr adoption-check:
    --seed repointing folderadr at a
    directory that already has an unrelated file matching the naming
    scheme is exactly as capable of silently adopting it as `config` is."""
    init.run(["--path", str(tmp_path)])
    new_folder = tmp_path / "unrelated-docs"
    new_folder.mkdir(parents=True)
    (new_folder / "ADR001V01-unrelated.md").write_bytes(b"hand written, never a real decision\n")

    seed = json.loads(init.default_repo_config_text())
    seed["folderadr"] = "unrelated-docs"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "folderadr-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1
    assert "ADR001V01-unrelated.md" in excinfo.value.data["adopted_files"][0]
    on_disk = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert on_disk["folderadr"] == "doc/adr"  # nothing was written


def test_init_seed_rejects_a_status_label_or_separator_change_when_decisions_already_exist(tmp_path):
    """ADR004V01: --seed replacing an already-existing repository's config
    is exactly as capable of breaking status-label/separator recognition
    of existing decisions as `config` is -- same shared guard."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    seed = json.loads(init.default_repo_config_text())
    seed["statusacc"] = "Approved"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["statusacc"], "existing_decisions": 1}
    on_disk = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert on_disk["statusacc"] == "Accepted"  # nothing was written


def test_init_seed_rejects_a_migrationpattern_change_when_a_legacy_decision_already_exists(tmp_path):
    """ADR004V02: the guard's own call site wiring, not just the shared
    function's internals -- --seed changing migrationpattern is exactly
    as capable of breaking legacy-scheme recognition as `config` is."""
    seed = json.loads(init.default_repo_config_text())
    seed["migrationpattern"] = "N00:04T04"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(seed_path)])
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / "0001T01.md").write_bytes(b"Legacy content\n")

    seed["migrationpattern"] = "N00:05T05"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["migrationpattern"], "existing_decisions": 1}


def test_init_seed_rejects_a_separator_change_that_would_adopt_an_unrelated_unrecognized_file(tmp_path):
    """Call-site wiring proof for the deferred finding closed alongside
    ADR004V0x -- --seed changing separator can silently adopt an
    unrelated file exactly the same way `config` can."""
    init.run(["--path", str(tmp_path)])
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / "0001_MyTitle.md").write_bytes(b"hand written, not a real decision file\n")

    seed = json.loads(init.default_repo_config_text())
    seed["separator"] = "_"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "separator-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1


def test_init_seed_status_or_separator_guard_wins_over_numbers_scan_incomplete(tmp_path, monkeypatch):
    """ADR004V02: reject_status_or_separator_change_if_decisions_exist
    runs BEFORE _max_existing_numbers inside _validate_and_write -- when
    a seed both changes a guarded field AND has an unreadable
    subdirectory, status-or-separator-change-scan-incomplete wins, never
    init-existing-numbers-scan-incomplete. Pins this order so a future
    reordering of the two checks can't silently swap which code callers
    see with no test failure; also the first test of this guard's own
    scan-incomplete path through `init --seed` at all (previously
    exercised only through `config`)."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    seed = json.loads(init.default_repo_config_text())
    seed["statusnew"] = "Draft"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "status-or-separator-change-scan-incomplete"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_init_seed_refuses_when_folderlog_is_a_junction_onto_folderadr(tmp_path):
    """--seed over an existing repository: a junction aliasing folderlog
    onto folderadr, planted inside the repo tree, must be refused by
    init's own reject_aliased_repo_folders check before the config is
    rewritten."""
    init.run(["--path", str(tmp_path)])
    folderadr_dir = tmp_path / "doc" / "adr"
    folderlog_dir = tmp_path / "doc" / "decision-log"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(folderlog_dir), str(folderadr_dir)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

    seed = json.loads(_default_config_text())
    seed["prefix"] = "SEED"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "folderadr-folderlog-alias-same-directory"
    assert load_repo_config(tmp_path / "adr-config.adrplus").prefix != "SEED"  # never committed


def test_init_seed_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """_max_existing_numbers
    feeds a real safety decision (lenseq/lenversion/lenrevision must fit
    every EXISTING number) -- a hidden, higher-numbered decision inside
    an unreadable subdirectory must never be silently under-reported."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    seed = json.loads(init.default_repo_config_text())
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "init-existing-numbers-scan-incomplete"


def test_init_seed_does_not_commit_folderadr_if_the_new_folder_cannot_be_created(tmp_path, monkeypatch):
    """The new folder is created BEFORE the config write commits -- a
    failure creating it aborts
    cleanly with the original config untouched, instead of committing the
    new folderadr first and leaving the repository pointing at a
    directory that doesn't exist."""
    init.run(["--path", str(tmp_path)])

    seed = json.loads(init.default_repo_config_text())
    seed["folderadr"] = "newfolder"
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    from pathlib import Path as PathType

    real_mkdir = PathType.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if self.name == "newfolder":
            raise PermissionError("Access is denied (simulated)")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "mkdir", failing_mkdir)

    with pytest.raises(CommandError):
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    on_disk = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert on_disk["folderadr"] == "doc/adr"  # unchanged -- nothing committed
    assert not (tmp_path / "newfolder").exists()


def test_init_refuses_when_config_already_exists_without_file(tmp_path):
    init.run(["--path", str(tmp_path)])

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-already-exists"


def test_init_with_seed_overwrites_using_custom_config(tmp_path):
    """Usability backlog item B2: init's own --file was renamed --seed --
    everywhere else in the CLI, --file means "the decision file to
    mutate"; here it meant "a config JSON to seed the repo with", a
    naming collision an agent generalizing across commands could
    reasonably get wrong. Confirmed with the user as a deliberate
    divergence from the reference tool's own `-f/--file` naming (decision-log:
    accepted-divergence--2026-09-15--init--file-flag-renamed-to-seed.md)."""
    custom = json.loads(_default_config_text())
    custom["folderadr"] = "decisions"
    file_path = tmp_path / "custom-config.json"
    file_path.write_text(json.dumps(custom), encoding="utf-8")

    result = init.run(["--path", str(tmp_path), "--seed", str(file_path)])

    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == json.dumps(custom)
    assert (tmp_path / "decisions").is_dir()
    assert str(tmp_path / "decisions") in result["created"]


def test_init_no_longer_accepts_the_old_file_flag_name(tmp_path):
    with pytest.raises(UsageError):
        init.run(["--path", str(tmp_path), "--file", str(tmp_path / "whatever.json")])


def test_init_describe_declares_seed_not_file():
    arguments = {argument["name"] for argument in init.describe()["arguments"]}

    assert "seed" in arguments
    assert "file" not in arguments


def test_init_describe_documents_the_installconfig_recommendation_warning():
    description = init.describe()["description"]

    assert "warnings" in description
    assert "installconfig" in description


def test_init_file_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(tmp_path / "missing.json")])

    assert excinfo.value.code == "config-file-not-found"


def test_init_invalid_config_schema_propagates(tmp_path):
    custom = json.loads(_default_config_text())
    del custom["lenseq"]
    file_path = tmp_path / "bad-config.json"
    file_path.write_text(json.dumps(custom), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(file_path)])

    assert excinfo.value.code == "config-missing-field"


def test_init_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path / "does-not-exist")])

    assert excinfo.value.code == "target-directory-not-found"


def test_init_missing_path_argument_is_usage_error():
    with pytest.raises(UsageError):
        init.run([])


def test_init_unknown_argument_is_usage_error(tmp_path):
    with pytest.raises(UsageError):
        init.run(["--path", str(tmp_path), "--bogus", "x"])


def test_init_rejects_digit_overflow_against_existing_decisions(tmp_path):
    existing_adr_dir = tmp_path / "doc" / "adr"
    existing_adr_dir.mkdir(parents=True)
    (existing_adr_dir / "ADR1234V01-preexisting.md").write_text("irrelevant", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "lenseq-too-small-for-existing-decisions"
    # The real number was only ever in `detail`
    # (stderr, free text) -- an agent automating "bump lenseq until it
    # fits" would have had to parse that text instead of reading `data`.
    assert excinfo.value.data == {"max_number": 1234, "lenseq": 3}


def test_init_rejects_version_digit_overflow_against_existing_decisions(tmp_path):
    existing_adr_dir = tmp_path / "doc" / "adr"
    existing_adr_dir.mkdir(parents=True)
    (existing_adr_dir / "ADR001V123-preexisting.md").write_text("irrelevant", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "lenversion-too-small-for-existing-decisions"
    assert excinfo.value.data == {"max_version": 123, "lenversion": 2}


def test_init_rejects_revision_digit_overflow_against_existing_decisions(tmp_path):
    seed = json.loads(_default_config_text())
    seed["lenrevision"] = 1
    seed_path = tmp_path / "seed-config.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    existing_adr_dir = tmp_path / "doc" / "adr"
    existing_adr_dir.mkdir(parents=True)
    (existing_adr_dir / "ADR001V01R12-preexisting.md").write_text("irrelevant", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(seed_path)])

    assert excinfo.value.code == "lenrevision-too-small-for-existing-decisions"
    assert excinfo.value.data == {"max_revision": 12, "lenrevision": 1}


def test_init_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    exit_code = main(["init", "--path", str(tmp_path)])

    assert exit_code == EXIT_SUCCESS
    assert (tmp_path / "adr-config.adrplus").exists()


def test_init_rejects_folderadr_traversal_outside_repository(tmp_path):
    """`folderadr: "../.."` passes config.py's schema check (it isn't
    absolute), but must still be caught at the point of use -- a hostile
    config (e.g. from a cloned repo) must never be able to make init create
    a directory outside the target repository."""
    custom = json.loads(_default_config_text())
    custom["folderadr"] = "../../escape"
    file_path = tmp_path / "custom-config.json"
    file_path.write_text(json.dumps(custom), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(file_path)])

    assert excinfo.value.code == "path-outside-repository"


def test_init_rejects_seed_file_with_invalid_utf8_bytes(tmp_path):
    """A second call site of the same class: init's own --seed read used
    a bare read_text(encoding="utf-8") too."""
    file_path = tmp_path / "custom-config.json"
    file_path.write_bytes(b'{"folderadr": "doc\xffadr"}')

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--seed", str(file_path)])

    assert excinfo.value.code == "config-invalid-encoding"


def test_init_with_language_seeds_localized_labels_and_template(tmp_path):
    """The reference tool's own `language` app setting doesn't just affect
    interactive UI text -- it also picks the DEFAULT header/status labels
    and template content baked into a newly init'd repo (read from a
    per-culture resource file; the default template file is swapped for
    a per-culture variant). Extracted verbatim from the reference tool's
    own resources, never hand-translated."""
    result = init.run(["--path", str(tmp_path), "--language", "pt-br"])

    config = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert config["statusnew"] == "Proposto"
    assert config["statusacc"] == "Aceito"
    assert config["headerversion"] == "Versão"
    assert config["headerscope"] == "Escopo"
    assert "Contexto e Declaração do Problema" in config["template"]
    # Everything NOT covered by the language pack keeps the built-in default.
    assert config["folderadr"] == "doc/adr"
    assert config["separator"] == "-"
    assert result["created"][0] == str(tmp_path / "adr-config.adrplus")


def test_init_rejects_unsupported_language(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--language", "klingon"])

    # Generic code, not init-specific: shared with installconfig's own
    # --language, since neither command has anything left to add once
    # the language itself isn't recognized.
    assert excinfo.value.code == "language-not-supported"


def test_init_uses_install_level_config_as_seed_when_present(tmp_path, monkeypatch):
    # tests/fixtures/adr-config.adrplus differs from the built-in default
    # in activeplugins (["AdrIndexer"] vs []) -- a distinguishing field
    # that proves this content was actually used, not a coincidence.
    install_text = (Path("tests") / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8")
    monkeypatch.setattr(init, "read_install_config_text", lambda: install_text)

    result = init.run(["--path", str(tmp_path)])

    config_path = tmp_path / "adr-config.adrplus"
    assert config_path.read_text(encoding="utf-8") == install_text
    assert load_repo_config(config_path).activeplugins == ["AdrIndexer"]
    assert result["created"][0] == str(config_path)


def test_init_rejects_language_when_install_level_config_exists(tmp_path, monkeypatch):
    install_text = (Path("tests") / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8")
    monkeypatch.setattr(init, "read_install_config_text", lambda: install_text)

    with pytest.raises(UsageError):
        init.run(["--path", str(tmp_path), "--language", "pt-br"])


def test_init_rejects_an_install_level_folderadr_that_collapses_onto_the_repository_root(tmp_path, monkeypatch):
    """The most dangerous entry point for the folderadr-collapse bug --
    'installconfig --folderadr' does NOT validate against a repository
    (there isn't one yet), so a poisoned per-user config would make every
    subsequent `init` on that machine (no --seed/--language given)
    silently create a repository whose own decisions folder equals its
    own root. The existing-decisions guard never engages either, since a
    fresh repo has zero decisions.

    ADR007V01: '.' has zero path components, a prefix of any folderlog
    value (explicit or computed-default) by construction -- the schema-
    level folderadr/folderlog containment guard now catches this even
    earlier than resolve_within's own path-outside-repository check."""
    from importlib import resources

    default_text = resources.files("adrpy.resources").joinpath("default_repo_config.json").read_text(encoding="utf-8")
    poisoned = json.loads(default_text)
    poisoned["folderadr"] = "."
    monkeypatch.setattr(init, "read_install_config_text", lambda: json.dumps(poisoned))

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-folderadr-folderlog-overlap"
    assert not (tmp_path / "adr-config.adrplus").exists()


def test_missing_target_directory_error_is_not_masked_by_a_corrupt_install_level_config(tmp_path, monkeypatch):
    """The install-level config read must not run unconditionally before
    target.is_dir() -- a corrupted per-user file would otherwise mask the
    real, relevant error with an unrelated schema-validation failure."""

    def _raise_corrupted():
        raise CommandError("config-invalid-json", "simulated corruption")

    monkeypatch.setattr(init, "read_install_config_text", _raise_corrupted)

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path / "does-not-exist")])

    assert excinfo.value.code == "target-directory-not-found"


def test_config_already_exists_error_is_not_masked_by_a_corrupt_install_level_config(tmp_path, monkeypatch):
    init.run(["--path", str(tmp_path)])

    def _raise_corrupted():
        raise CommandError("config-invalid-json", "simulated corruption")

    monkeypatch.setattr(init, "read_install_config_text", _raise_corrupted)

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-already-exists"


def test_init_seed_does_not_consult_install_level_config(tmp_path, monkeypatch):
    def _fail_if_called():
        raise AssertionError("install-level config must not be consulted when --seed is given")

    monkeypatch.setattr(init, "read_install_config_text", _fail_if_called)
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(_default_config_text(), encoding="utf-8")

    init.run(["--path", str(tmp_path), "--seed", str(seed_path)])


@pytest.mark.parametrize("language", init.SUPPORTED_LANGUAGES)
def test_init_accepts_every_supported_language(tmp_path, language):
    """Every language pack must itself pass the real schema validation
    (label length limits, ASCII-only prefix, ...) -- not just pt-br."""
    result = init.run(["--path", str(tmp_path), "--language", language])

    assert result["created"][0] == str(tmp_path / "adr-config.adrplus")
    config = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert config["prefix"] == "ADR"  # every language pack's prefix is ASCII "ADR"


def test_bare_init_and_explicit_language_en_us_produce_byte_identical_template(tmp_path, tmp_path_factory):
    """default_repo_config.json's own `template` field used CRLF
    line endings while every one of the 11 language packs (including
    en-us.json, "Defaults to en-us" per init's own describe()) used bare
    LF -- so a bare `init` and an explicit `init --language en-us`
    produced the same prose but byte-different adr-config.adrplus files."""
    bare_dir = tmp_path_factory.mktemp("bare")
    lang_dir = tmp_path_factory.mktemp("lang")
    init.run(["--path", str(bare_dir)])
    init.run(["--path", str(lang_dir), "--language", "en-us"])

    bare_template = json.loads((bare_dir / "adr-config.adrplus").read_text(encoding="utf-8"))["template"]
    lang_template = json.loads((lang_dir / "adr-config.adrplus").read_text(encoding="utf-8"))["template"]
    assert bare_template == lang_template


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_init_reports_a_candidate_excluded_via_a_windows_junction(tmp_path):
    """Init's own pre-existing-
    decisions scan (_max_existing_numbers) must not drop an is_within-
    excluded candidate with zero signal, same as scan_decisions/explore."""
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "ADR001V01-victim.md").write_text("# Victim\n", encoding="utf-8")
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    result_data = init.run(["--path", str(tmp_path)])

    assert any("escapes the repository boundary" in w for w in result_data["warnings"])


def test_init_rejects_language_combined_with_seed(tmp_path):
    file_path = tmp_path / "custom-config.json"
    file_path.write_text(_default_config_text(), encoding="utf-8")

    with pytest.raises(UsageError):
        init.run(["--path", str(tmp_path), "--seed", str(file_path), "--language", "pt-br"])
