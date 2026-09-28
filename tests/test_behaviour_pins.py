"""Behaviour no other test pinned, found by mutation testing core/fs.py,
core/naming.py and core/consistency.py: each test here passes on the code
and fails on a mutant the rest of the suite let through -- error fields
(file, related_files, data, warnings), orders other than "number 1 first",
retry backoff, and the failure paths of the scan and the orphan sweeps."""

import errno
import os
import stat
import time
from pathlib import Path

import pytest

from adrpy.core import consistency, fs, naming
from adrpy.core.consistency import Snapshot, check_repository
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import build_header

from conftest import D, decision_record, make_repo

HEX = "0123456789abcdef"


def _symlink(link, target):
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("creating a symlink needs a privilege this host does not grant")


class _Listing:
    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc):
        return False


def _sorted_scandir(monkeypatch, *, blocked=(), reverse=False, wrap=None):
    real = os.scandir

    def fake(path="."):
        if os.path.basename(os.fspath(path)) in blocked:
            raise PermissionError(13, "Access is denied", os.fspath(path))
        with real(path) as it:
            entries = sorted(it, key=lambda e: e.name, reverse=reverse)
        if wrap:
            entries = [wrap(e) for e in entries]
        return _Listing(entries)

    monkeypatch.setattr(fs.os, "scandir", fake)


# ------------------------------------------------------------------ fs --


def test_make_dirs_on_an_existing_folder_returns_none_and_rollback_keeps_it(tmp_path):
    folder = tmp_path / "existing" / "empty"
    folder.mkdir(parents=True)
    top = fs.make_dirs(folder)
    assert top is None
    fs.remove_created_dirs(folder, top)
    assert folder.is_dir() and (tmp_path / "existing").is_dir()


def test_unlink_with_retry_of_an_absent_path_is_fine(tmp_path):
    fs.unlink_with_retry(tmp_path / "absent.md")


def test_discard_of_an_absent_temp_reports_it_gone(tmp_path):
    assert fs._discard(tmp_path / "absent.tmp") is True


def _record_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fs.time, "sleep", sleeps.append)
    return sleeps


def test_prepare_write_retries_with_exponential_backoff(tmp_path, monkeypatch):
    sleeps = _record_sleeps(monkeypatch)
    calls = {"n": 0}
    real_open = open

    def flaky_open(path, mode="r", *a, **k):
        if str(path).endswith(".tmp") and "w" in mode and calls["n"] < 3:
            calls["n"] += 1
            raise PermissionError(13, "busy", str(path))
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(fs, "open", flaky_open, raising=False)
    prepared = fs.prepare_write(tmp_path / "d.md", b"x")
    fs.discard_write(prepared)
    assert sleeps == [0.05, 0.1, 0.2]


def test_commit_write_retries_with_exponential_backoff(tmp_path, monkeypatch):
    sleeps = _record_sleeps(monkeypatch)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        if calls["n"] < 3:
            calls["n"] += 1
            raise PermissionError(13, "busy", str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(fs.os, "replace", flaky_replace)
    fs.commit_write(fs.prepare_write(tmp_path / "d.md", b"x"))
    assert sleeps == [0.05, 0.1, 0.2]


def test_no_link_fallback_whose_reservation_cannot_be_removed_names_it(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_IS_WINDOWS", False)
    monkeypatch.setattr(fs.os, "link", lambda s, d: (_ for _ in ()).throw(OSError(errno.EPERM, "no links")))
    monkeypatch.setattr(fs.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(13, "busy", str(d))))
    target = tmp_path / "d.md"
    real_discard = fs._discard
    monkeypatch.setattr(fs, "_discard", lambda p: False if Path(p) == target else real_discard(p))
    with pytest.raises(OSError) as excinfo:
        fs.commit_write(fs.prepare_write(target, b"x"), exclusive=True)
    error = excinfo.value
    assert not isinstance(error, PermissionError)
    assert error.errno == errno.EIO
    assert error.strerror.endswith("could not be removed; remove it by hand")
    assert error.filename == str(target)


def test_an_entry_that_cannot_be_inspected_counts_as_a_link():
    class Entry:
        def is_symlink(self):
            raise OSError(errno.EIO, "gone")

    assert fs._is_link(Entry()) is True


def _old_temp(folder, name):
    path = folder / f"{name}.md.{HEX}.tmp"
    path.write_text("stale")
    old = time.time() - 120
    os.utime(path, (old, old))
    return path


def test_orphan_sweep_does_not_stop_at_a_link_carrying_a_temp_name(tmp_path):
    link = tmp_path / f"a.md.{HEX}.tmp"
    _symlink(link, tmp_path / "elsewhere")
    real = _old_temp(tmp_path, "b")
    assert fs._remove_orphans([link, real], 30, None) == [real]


def test_orphan_sweep_does_not_stop_at_a_vanished_candidate(tmp_path):
    real = _old_temp(tmp_path, "b")
    assert fs._remove_orphans([tmp_path / f"gone.md.{HEX}.tmp", real], 30, None) == [real]


def test_orphan_sweep_reports_an_unstatable_candidate_and_goes_on(tmp_path, monkeypatch):
    blocked = _old_temp(tmp_path, "a")
    real = _old_temp(tmp_path, "b")
    real_lstat = Path.lstat

    def lstat(self):
        if self == blocked:
            raise PermissionError(13, "denied", str(self))
        return real_lstat(self)

    monkeypatch.setattr(Path, "lstat", lstat)
    warnings = []
    assert fs._remove_orphans([blocked, real], 30, warnings) == [real]
    assert len(warnings) == 1 and warnings[0].endswith(f": {blocked.name}.")


def test_orphan_sweep_age_boundary_is_strict(tmp_path, monkeypatch):
    path = tmp_path / f"a.md.{HEX}.tmp"
    path.write_text("x")
    now = 2_000_000_000.0
    os.utime(path, (now - 30, now - 30))
    monkeypatch.setattr(fs.time, "time", lambda: now)
    assert fs._remove_orphans([path], 30, None) == []


def test_orphan_sweep_counts_a_temp_gone_before_its_unlink_as_removed(tmp_path):
    real = _old_temp(tmp_path, "a")
    info = real.lstat()

    class Vanishing:
        name = real.name

        def lstat(self):
            return info

        def unlink(self, missing_ok=False):
            if not missing_ok:
                raise FileNotFoundError(2, "gone")

    warnings = []
    removed = fs._remove_orphans([Vanishing()], 30, warnings)
    assert len(removed) == 1 and warnings == []


def test_orphan_sweep_warning_lists_names_comma_separated(tmp_path, monkeypatch):
    a, b = _old_temp(tmp_path, "a"), _old_temp(tmp_path, "b")
    monkeypatch.setattr(Path, "lstat", lambda self: (_ for _ in ()).throw(PermissionError(13, "denied")))
    warnings = []
    fs._remove_orphans([a, b], 30, warnings)
    assert warnings[0].endswith(f": {a.name}, {b.name}.")


def test_scan_goes_on_after_an_unreadable_directory(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x.md").write_text("x")
    _sorted_scandir(monkeypatch, blocked={"a"})
    scan = fs.scan_tree(tmp_path)
    assert [p.name for p in scan.markdown] == ["x.md"]
    assert len(scan.unreadable) == 1


def test_scan_goes_on_after_an_excluded_file_link(tmp_path, monkeypatch):
    folder = tmp_path / "decisions"
    folder.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("o")
    _symlink(folder / "a.md", outside)
    (folder / "b.md").write_text("b")
    (folder / "sub").mkdir()
    (folder / "sub" / "c.md").write_text("c")
    _sorted_scandir(monkeypatch)
    scan = fs.scan_tree(folder)
    assert sorted(p.name for p in scan.markdown) == ["b.md", "c.md"]
    assert [p.name for p in scan.excluded] == ["a.md"]


def test_scan_order_is_os_walk_depth_first(tmp_path, monkeypatch):
    for rel in ("a/x.md", "a/b/y.md", "c/z.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    _sorted_scandir(monkeypatch)
    assert [p.name for p in fs.scan_tree(tmp_path).markdown] == ["x.md", "y.md", "z.md"]


def test_scan_of_a_folder_that_cannot_be_resolved_excludes_instead_of_crashing(tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text("x")
    real_resolve = Path.resolve

    def resolve(self, *a, **k):
        if self == tmp_path:
            raise OSError(errno.EIO, "cannot resolve")
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", resolve)
    scan = fs.scan_tree(tmp_path)
    assert scan.markdown == ()


def test_scan_keeps_a_file_whose_is_dir_fails(tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text("x")

    class Wrapped:
        def __init__(self, entry):
            self._e = entry
            self.name = entry.name

        def is_dir(self):
            raise OSError(errno.EIO, "flaky")

        def __getattr__(self, attr):
            return getattr(self._e, attr)

    _sorted_scandir(monkeypatch, wrap=Wrapped)
    scan = fs.scan_tree(tmp_path)
    assert [p.name for p in scan.markdown] == ["x.md"] and scan.unreadable == ()


# -------------------------------------------------------------- naming --


def _legacy_config(tmp_path, pattern):
    return make_repo(tmp_path, config={"migrationpattern": pattern}).config


def test_legacy_name_exactly_as_long_as_its_number(tmp_path):
    parsed = naming.parse_legacy_filename("0001.md", _legacy_config(tmp_path, "N00:04T04"))
    assert (parsed.number, parsed.title) == (1, "")


def test_legacy_name_shorter_than_its_number_range_with_title_first(tmp_path):
    assert naming.parse_legacy_filename("ab12.md", _legacy_config(tmp_path, "N02:04T00")) is None


def test_legacy_name_exactly_as_long_as_its_version(tmp_path):
    parsed = naming.parse_legacy_filename("000101.md", _legacy_config(tmp_path, "N00:04T06V04:02"))
    assert parsed.version == 1


def test_legacy_name_ending_inside_its_version_range(tmp_path):
    name = "0001" + "x" * 16 + "5.md"
    assert naming.parse_legacy_filename(name, _legacy_config(tmp_path, "N00:04T04V20:02")) is None


def test_legacy_name_exactly_as_long_as_its_revision(tmp_path):
    parsed = naming.parse_legacy_filename("00010102.md", _legacy_config(tmp_path, "N00:04T08V04:02R06:02"))
    assert parsed.revision == 2


def test_legacy_name_ending_inside_its_revision_range(tmp_path):
    name = "0001" + "x" * 16 + "5.md"
    assert naming.parse_legacy_filename(name, _legacy_config(tmp_path, "N00:04T04R20:02")) is None


def test_build_filename_with_an_empty_prefix(tmp_path):
    repo = make_repo(tmp_path, config={"prefix": ""})
    name = naming.build_filename(repo.config, decision_record(repo.config, D(1)))
    assert name[0].isdigit()


def test_build_filename_with_a_one_digit_revision(tmp_path):
    repo = make_repo(tmp_path, config={"lenrevision": 1})
    name = naming.build_filename(repo.config, decision_record(repo.config, D(1)))
    assert "R1" in name


def test_a_title_that_would_read_back_as_a_successor_is_refused(tmp_path):
    repo = make_repo(tmp_path, config={"separator": ".", "casetransform": "CamelCase"})
    with pytest.raises(CommandError) as excinfo:
        naming.build_filename(repo.config, decision_record(repo.config, D(1, title="a..5")))
    error = excinfo.value
    assert error.code == FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME
    assert set(error.data) == {"filename"} and error.data["filename"].endswith("..5.md")
    assert error.detail.endswith("which would permanently orphan it.")


def test_too_long_filename_carries_data_and_warnings():
    name = "a" * 300 + ".md"
    with pytest.raises(CommandError) as excinfo:
        naming.reject_too_long_filename(name, "shorten it", warnings=["w"])
    assert excinfo.value.data == {"filename": name}
    assert excinfo.value.warnings == ["w"]
    assert "(255 bytes for one name, the strictest of NTFS, ext4 and APFS," in excinfo.value.detail


# --------------------------------------------------------- consistency --


def _errors(repo):
    return check_repository(repo.folder, repo.config)[1]


def test_a_dangling_superseded_cell_after_a_non_superseded_decision_is_reported(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, state="accepted"), D(2, state="superseded", successor=9)])
    assert [(e["code"], e["file"]) for e in _errors(repo)] == [
        (FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR, str(repo.paths[1]))
    ]


def _conflicted(tmp_path, spec):
    probe = make_repo(tmp_path / "probe")
    lines = build_header(probe.config, decision_record(probe.config, spec)).splitlines()
    lines.insert(4, "<<<<<<< HEAD")
    return "\n".join(lines) + "\n"


def test_a_conflicted_successor_does_not_hide_a_later_dangling_superseded_cell(tmp_path):
    successor = D(2, state="accepted", suffix=1)
    repo = make_repo(
        tmp_path / "repo",
        files=[
            D(1, state="superseded", successor=2),
            D(2, suffix=1, content=_conflicted(tmp_path, successor)),
            D(3, state="superseded", successor=9),
        ],
    )
    codes = sorted(e["code"] for e in _errors(repo))
    assert codes == sorted([FailureCodes.MERGE_CONFLICT_MARKERS, FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR])


def test_pending_duplicate_names_its_files(tmp_path):
    repo = make_repo(tmp_path, files=[D(1), D(1, version=2)])
    (error,) = [e for e in _errors(repo) if e["code"] == FailureCodes.PENDING_DUPLICATE]
    assert error["file"] == str(repo.paths[0])
    assert error["related_files"] == [str(repo.paths[1])]


def test_invalid_status_combination_names_its_file(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, state="proposed", change="Superseded", successor=2)])
    (error,) = [e for e in _errors(repo) if e["code"] == FailureCodes.INVALID_STATUS_COMBINATION]
    assert error["file"] == str(repo.paths[0])


def test_an_unreadable_decision_does_not_hide_the_next_ones(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, files=[D(1), D(2, content="no header here\n")])
    real_read = consistency.read_header_lines_with_report

    def flaky(path, *a, **k):
        if path == repo.paths[0]:
            raise PermissionError(13, "Access is denied", str(path))
        return real_read(path, *a, **k)

    monkeypatch.setattr(consistency, "read_header_lines_with_report", flaky)
    _sorted_scandir(monkeypatch)
    errors = _errors(repo)
    assert [(e["code"], e["file"]) for e in errors] == [
        (FailureCodes.SCAN_INCOMPLETE, str(repo.paths[0])),
        (FailureCodes.NO_HEADER, str(repo.paths[1])),
    ]
    assert "Access is denied" in errors[0]["detail"]


def test_snapshot_carries_the_files_excluded_for_escaping(tmp_path):
    repo = make_repo(tmp_path, files=[D(1)])
    outside = tmp_path / "outside.md"
    outside.write_text("o")
    _symlink(repo.folder / "ADR0009V01-escape.md", outside)
    snapshot, _ = check_repository(repo.folder, repo.config)
    assert [p.name for p in snapshot.excluded] == ["ADR0009V01-escape.md"]


def test_decisions_with_the_same_key_are_ordered_by_path(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, files=[D(1, title="Alpha"), D(1, title="Beta")])
    _sorted_scandir(monkeypatch, reverse=True)
    snapshot, _ = check_repository(repo.folder, repo.config)
    paths = [str(d.path) for d in snapshot.decisions]
    assert paths == sorted(paths)


def test_successor_hint_finishes_the_supersede_on_the_live_member_not_a_rejected_newer_one(tmp_path):
    repo = make_repo(
        tmp_path,
        files=[D(1, state="accepted"), D(1, version=2, state="rejected"), D(2, state="accepted", suffix=1)],
    )
    (error,) = [e for e in _errors(repo) if e["code"] == FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR]
    assert f"finish the supersede: in {repo.paths[0]}," in error["hint"]


def test_superseded_not_live_hint_ending_depends_on_whether_the_blocker_can_carry(tmp_path):
    sentence = " Only an Accepted member can carry the Superseded cell, so it cannot move to the newer one."
    carry = make_repo(
        tmp_path / "carry",
        files=[D(1, state="superseded", successor=3), D(1, version=2, state="accepted"), D(3, suffix=1)],
    )
    (error,) = [e for e in _errors(carry) if e["code"] == FailureCodes.SUPERSEDED_NOT_LIVE]
    label = carry.config.headertitlestatuschanged
    assert error["hint"].startswith("A Superseded decision is not the live member of its family: a newer member")
    assert f"drop the newer member: in {carry.paths[1]}, replace the row starting '|{label}|' with: |{label}|" in error["hint"]
    assert not error["hint"].endswith(sentence)
    assert error["hint"].endswith(".")
    assert "order of preference: 1) move the Superseded cell" in error["hint"]
    assert "; 2) drop the newer member" in error["hint"]

    nocarry = make_repo(
        tmp_path / "nocarry",
        files=[D(1, state="superseded", successor=3), D(1, version=2, state="proposed"), D(3, suffix=1)],
    )
    (error,) = [e for e in _errors(nocarry) if e["code"] == FailureCodes.SUPERSEDED_NOT_LIVE]
    assert error["hint"].endswith(sentence)
    assert "1) drop the newer member" in error["hint"]


def test_unrecognized_warning_lists_single_digit_and_non_ascii_names(tmp_path):
    repo = make_repo(tmp_path, config={"migrationpattern": "N00:04T04"})
    (repo.folder / "1-x.md").write_text("x")
    (repo.folder / "2é.md").write_text("x")
    warning = consistency.unrecognized_decision_like_warning(fs.scan_tree(repo.folder), repo.config)
    assert warning.startswith(f"2 .md file(s) in {repo.config.folderadr} are not recognized: 1-x.md, 2é.md.")


def test_note_shared_numbers_without_the_phase_warning_is_a_no_op(tmp_path):
    config = make_repo(tmp_path, config={"migrationpattern": "N00:04T04"}).config
    snapshot = Snapshot(decisions=(), by_number={}, unheadered_legacy=(Path("0001-old.md"),))
    warnings = []
    consistency.note_shared_numbers(warnings, snapshot, config, [(1, True)])
    assert warnings == []


def test_init_counts_every_number_even_after_an_unreadable_decision(tmp_path, monkeypatch):
    from adrpy.cli import init as init_cli

    repo = make_repo(tmp_path, files=[D(1), D(999)])
    real_read = consistency.read_header_lines_with_report

    def flaky(path, *a, **k):
        if path == repo.paths[0]:
            raise PermissionError(13, "Access is denied", str(path))
        return real_read(path, *a, **k)

    monkeypatch.setattr(consistency, "read_header_lines_with_report", flaky)
    _sorted_scandir(monkeypatch)
    assert init_cli._max_existing_numbers(repo.root, repo.config)[0] == 999


def test_scan_of_an_unresolvable_folder_excludes_its_subdirectories_too(tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text("x")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    real_resolve = Path.resolve

    def resolve(self, *a, **k):
        if self == tmp_path:
            raise OSError(errno.EIO, "cannot resolve")
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", resolve)
    _sorted_scandir(monkeypatch)
    scan = fs.scan_tree(tmp_path)
    assert scan.markdown == ()
    assert sorted(p.name for p in scan.excluded) == ["a", "b", "x.md"]
