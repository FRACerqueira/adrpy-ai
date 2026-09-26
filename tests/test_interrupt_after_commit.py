"""A Ctrl+C that reaches Python right after the rename/replace that
commits a write (CPython raises it at the first check after the syscall
returns, still inside core/fs.commit_write) must not make a file that is
on disk count as not written. Every write that reports what it wrote
(supersede, reject, log, migrate) decides it from the target's bytes: a
prepared write whose digest matches the target counts as applied.

The interrupt is simulated exactly there: the real os.replace/os.rename
(or os.link, an exclusive create on POSIX) runs, then KeyboardInterrupt
is raised, once, for the chosen target."""

import json
import os
from pathlib import Path

from adrpy.__main__ import main
from adrpy.cli import approve, init, new, supersede
from adrpy.core import fs, lifecycle


def _interrupt_after_moving_onto(monkeypatch, is_target):
    fired = {"done": False}
    for name in ("replace", "rename", "link"):
        real = getattr(os, name)

        def moved_then_interrupted(src, dst, *args, _real=real, **kwargs):
            result = _real(src, dst, *args, **kwargs)
            if not fired["done"] and is_target(Path(dst)):
                fired["done"] = True
                raise KeyboardInterrupt()
            return result

        monkeypatch.setattr(fs.os, name, moved_then_interrupted)


def _run(capsys, *argv):
    capsys.readouterr()
    main(list(argv))
    return json.loads(capsys.readouterr().out)


def _accepted(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    approve.run(["--file", str(path), "--refdate", "2026-01-02"])
    return path


def _check(capsys, tmp_path):
    return _run(capsys, "check", "--path", str(tmp_path))


def test_supersede_interrupted_right_after_creating_the_successor_says_it_was_written(tmp_path, monkeypatch, capsys):
    path = _accepted(tmp_path)
    successor = path.parent / "ADR002V01-first-decision--001.md"
    _interrupt_after_moving_onto(monkeypatch, lambda dst: dst.name == successor.name)

    response = _run(capsys, "supersede", "--file", str(path), "--refdate", "2026-01-05")

    assert response["code"] == "interrupted"
    assert response["data"]["applied"] == [str(successor)]
    assert response["data"]["pending"] == [str(path)]
    assert set(response["data"]["repair"]) == {"file", "row"}
    assert successor.exists()


def test_supersede_interrupted_right_after_the_last_write_says_everything_was_written(tmp_path, monkeypatch, capsys):
    path = _accepted(tmp_path)
    successor = path.parent / "ADR002V01-first-decision--001.md"
    _interrupt_after_moving_onto(monkeypatch, lambda dst: dst.name == path.name)

    response = _run(capsys, "supersede", "--file", str(path), "--refdate", "2026-01-05")

    assert response["code"] == "interrupted"
    assert response["data"]["applied"] == [str(successor), str(path)]
    assert response["data"]["pending"] == []
    # The repository is consistent: nothing to repair, no hint saying
    # otherwise (following one would break it).
    assert "repair" not in response["data"]
    assert "inconsistent" not in response["detail"]
    monkeypatch.undo()
    assert _check(capsys, tmp_path)["success"] is True


def test_an_interrupt_after_every_commit_is_not_reported_as_an_inconsistent_repository(tmp_path, monkeypatch, capsys):
    path = _accepted(tmp_path)
    real_retry_warning = lifecycle.retry_warning
    calls = {"n": 0}

    def interrupted_on_the_last(attempts):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt()
        return real_retry_warning(attempts)

    monkeypatch.setattr(lifecycle, "retry_warning", interrupted_on_the_last)

    response = _run(capsys, "supersede", "--file", str(path), "--refdate", "2026-01-05")

    assert response["code"] == "interrupted"
    assert response["data"]["pending"] == []
    assert "repair" not in response["data"]
    assert "inconsistent" not in response["detail"]


def test_reject_interrupted_right_after_reverting_the_predecessor_says_it_was_written(tmp_path, monkeypatch, capsys):
    path = _accepted(tmp_path)
    created = supersede.run(["--file", str(path), "--refdate", "2026-01-05"])["created"]
    _interrupt_after_moving_onto(monkeypatch, lambda dst: dst.name == path.name)

    response = _run(capsys, "reject", "--file", created, "--refdate", "2026-01-06")

    assert response["code"] == "interrupted"
    assert response["data"]["applied"] == [str(path)]
    assert response["data"]["pending"] == [created]
    assert "|Superseded||" in path.read_text(encoding="utf-8")


def test_log_interrupted_right_after_writing_the_entry_names_the_entry(tmp_path, monkeypatch, capsys):
    init.run(["--path", str(tmp_path)])
    entry = tmp_path / "doc" / "decision-log" / "2026-09-18--scope-note--lock--x.md"
    _interrupt_after_moving_onto(monkeypatch, lambda dst: dst.name == entry.name)

    response = _run(
        capsys, "log", "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock",
        "--slug", "x", "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
    )

    assert response["code"] == "interrupted"
    assert response["data"] == {"file": str(entry)}
    assert entry.exists()


def test_log_interrupted_before_the_entry_lands_does_not_name_it(tmp_path, monkeypatch, capsys):
    init.run(["--path", str(tmp_path)])
    entry = tmp_path / "doc" / "decision-log" / "2026-09-18--scope-note--lock--x.md"
    for name in ("replace", "rename", "link"):
        real = getattr(os, name)

        def interrupted_instead(src, dst, *args, _real=real, **kwargs):
            if Path(dst).name == entry.name:
                raise KeyboardInterrupt()
            return _real(src, dst, *args, **kwargs)

        monkeypatch.setattr(fs.os, name, interrupted_instead)

    response = _run(
        capsys, "log", "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock",
        "--slug", "x", "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
    )

    assert response["code"] == "interrupted"
    assert "data" not in response
    assert not entry.exists()


def _repo_with_pattern(tmp_path, pattern):
    seed = json.loads((Path(__file__).parent / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8"))
    seed["migrationpattern"] = pattern
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(seed), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(seed_file)])
    adr = tmp_path / "doc" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    legacy = adr / "0001First.md"
    legacy.write_bytes(b"# First\n")
    return legacy


def test_migrate_interrupted_right_after_writing_a_file_reports_it_migrated(tmp_path, monkeypatch, capsys):
    legacy = _repo_with_pattern(tmp_path, "N00:04T04")
    _interrupt_after_moving_onto(monkeypatch, lambda dst: dst.name == legacy.name)

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["code"] == "interrupted"
    assert response["data"]["results"] == [{"file": str(legacy), "status": "migrated", "error": None}]


def test_migrate_interrupted_right_after_persisting_the_fallback_pattern_says_so(tmp_path, monkeypatch, capsys):
    from adrpy.cli import migrate

    _repo_with_pattern(tmp_path, "")
    fallback = json.loads((Path(__file__).parent / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8"))
    fallback["migrationpattern"] = "N00:04T04"
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: json.dumps(fallback))
    _interrupt_after_moving_onto(monkeypatch, lambda dst: dst.name == "adr-config.adrplus")

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["code"] == "interrupted"
    assert response["data"]["migrationpattern_persisted"] == "N00:04T04"


def _fail_next_read_of(monkeypatch, name, error):
    """The next binary open of a file called `name` raises `error`, once --
    armed only after the interrupt fired, so only the handler's own read
    of the target sees it."""
    state = {"armed": False}
    real_open = Path.open

    def open_once_failing(self, mode="r", *args, **kwargs):
        if state["armed"] and self.name == name and "b" in mode:
            state["armed"] = False
            raise error
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_once_failing)
    return state


def _interrupt_after_moving_onto_then(monkeypatch, is_target, then):
    for name in ("replace", "rename", "link"):
        real = getattr(os, name)

        def moved_then_interrupted(src, dst, *args, _real=real, **kwargs):
            result = _real(src, dst, *args, **kwargs)
            if is_target(Path(dst)) and not then.get("fired"):
                then["fired"] = True
                then["armed"] = True
                raise KeyboardInterrupt()
            return result

        monkeypatch.setattr(fs.os, name, moved_then_interrupted)


def test_a_transient_permission_error_reading_back_a_written_file_still_counts_it_written(tmp_path, monkeypatch, capsys):
    # An antivirus or indexer holding the file just renamed onto: the
    # handler's read-back retries like every other read.
    path = _accepted(tmp_path)
    successor = path.parent / "ADR002V01-first-decision--001.md"
    state = _fail_next_read_of(monkeypatch, path.name, PermissionError(13, "Permission denied"))
    _interrupt_after_moving_onto_then(monkeypatch, lambda dst: dst.name == path.name, state)

    response = _run(capsys, "supersede", "--file", str(path), "--refdate", "2026-01-05")

    assert response["code"] == "interrupted"
    assert response["data"]["applied"] == [str(successor), str(path)]
    assert response["data"]["pending"] == []


def test_a_second_interrupt_while_reading_back_keeps_what_was_already_counted(tmp_path, monkeypatch, capsys):
    path = _accepted(tmp_path)
    successor = path.parent / "ADR002V01-first-decision--001.md"
    state = _fail_next_read_of(monkeypatch, path.name, KeyboardInterrupt())
    _interrupt_after_moving_onto_then(monkeypatch, lambda dst: dst.name == path.name, state)

    response = _run(capsys, "supersede", "--file", str(path), "--refdate", "2026-01-05")

    assert response["code"] == "interrupted"
    # The one being checked is not confirmed; what was counted stays.
    assert response["data"]["applied"] == [str(successor)]
    assert response["data"]["pending"] == [str(path)]


def _repo_with_two_legacy_files(tmp_path):
    first = _repo_with_pattern(tmp_path, "N00:04T04")
    second = first.parent / "0002Second.md"
    second.write_bytes(b"# Second\n")
    return first, second


def test_migrate_processes_the_files_in_name_order_whatever_order_the_folder_lists_them(tmp_path, monkeypatch, capsys):
    # NTFS and APFS list a folder by name, ext4 in hash order: the
    # results, and what an interrupt leaves migrated, must not depend on it.
    first, second = _repo_with_two_legacy_files(tmp_path)
    real_scandir = os.scandir

    class Listing(list):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def reversed_listing(*args, **kwargs):
        with real_scandir(*args, **kwargs) as listing:
            return Listing(sorted(listing, key=lambda entry: entry.name, reverse=True))

    monkeypatch.setattr(fs.os, "scandir", reversed_listing)

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["data"]["migrated"] == [str(first), str(second)]


def test_migrate_keeps_its_results_when_a_second_interrupt_arrives_while_reading_back(tmp_path, monkeypatch, capsys):
    first, second = _repo_with_two_legacy_files(tmp_path)
    state = _fail_next_read_of(monkeypatch, second.name, KeyboardInterrupt())
    _interrupt_after_moving_onto_then(monkeypatch, lambda dst: dst.name == second.name, state)

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["code"] == "interrupted"
    assert {"file": str(first), "status": "migrated", "error": None} in response["data"]["results"]


def test_migrate_reports_what_it_migrated_when_an_unexpected_error_stops_it(tmp_path, monkeypatch, capsys):
    first, second = _repo_with_two_legacy_files(tmp_path)
    real = os.replace

    def unexpected_on_the_second(src, dst, *args, **kwargs):
        if Path(dst).name == second.name:
            raise RuntimeError("boom")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(fs.os, "replace", unexpected_on_the_second)

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["code"] == "interrupted"
    assert response["detail"] == "Interrupted (boom)."
    assert response["data"]["results"] == [{"file": str(first), "status": "migrated", "error": None}]


def test_migrate_never_reports_a_failed_file_twice(tmp_path, monkeypatch, capsys):
    from adrpy.cli import migrate

    first, second = _repo_with_two_legacy_files(tmp_path)
    real_replace = os.replace
    real_landed = migrate.write_landed
    calls = {"landed": 0}

    def replace_then_fail(src, dst, *args, **kwargs):
        result = real_replace(src, dst, *args, **kwargs)
        if Path(dst).name == first.name:
            raise OSError(5, "I/O error")
        return result

    def not_seen_the_first_time(prepared):
        calls["landed"] += 1
        return False if calls["landed"] == 1 else real_landed(prepared)

    real_prepare = migrate.prepare_write

    def interrupted_preparing_the_second(path, data):
        if Path(path).name == second.name:
            raise KeyboardInterrupt()
        return real_prepare(path, data)

    monkeypatch.setattr(fs.os, "replace", replace_then_fail)
    monkeypatch.setattr(migrate, "write_landed", not_seen_the_first_time)
    monkeypatch.setattr(migrate, "prepare_write", interrupted_preparing_the_second)

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["code"] == "interrupted"
    files = [result["file"] for result in response["data"]["results"]]
    assert files == [str(first)]
    assert response["data"]["results"][0]["status"] == "failed"


def test_a_first_interrupt_while_migrate_checks_a_failed_write_stops_the_run(tmp_path, monkeypatch, capsys):
    # Outside an interrupt handler (a write that raised after its replace),
    # a Ctrl+C during the check is the user's first one: it must stop the
    # run, not be taken as "not written" with the next files migrated.
    first, second = _repo_with_two_legacy_files(tmp_path)
    state = _fail_next_read_of(monkeypatch, first.name, KeyboardInterrupt())
    real = os.replace

    def replace_then_fail(src, dst, *args, **kwargs):
        result = real(src, dst, *args, **kwargs)
        if Path(dst).name == first.name and not state.get("fired"):
            state["fired"] = True
            state["armed"] = True
            raise OSError(5, "I/O error")
        return result

    monkeypatch.setattr(fs.os, "replace", replace_then_fail)

    response = _run(capsys, "migrate", "--path", str(tmp_path))

    assert response["code"] == "interrupted"
    assert second.read_bytes() == b"# Second\n"
