import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, HeaderParseResult, build_header
from adrpy.core.lifecycle import (
    family_members,
    find_by_unique_title,
    ineligibility_reason_for_approve_or_reject,
    ineligibility_reason_for_supersede,
    ineligibility_reason_for_undo,
    ineligibility_reason_for_version_or_revise,
    load_target,
    next_number,
    read_body,
    read_header_lines,
    read_header_lines_with_report,
    reject_folderadr_change_if_decisions_exist,
    resolve_repo_and_target,
    resolve_target_and_config,
    rewrite_status_field,
    scan_decisions,
    stream_normalized_body_chunks,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)

import json

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def test_validate_refdate_not_in_future_accepts_today():
    validate_refdate_not_in_future(date.today())


def test_validate_refdate_not_in_future_rejects_tomorrow():
    with pytest.raises(CommandError) as excinfo:
        validate_refdate_not_in_future(date.today() + timedelta(days=1))

    assert excinfo.value.code == "refdate-in-future"


def test_validate_refdate_not_before_accepts_same_day():
    validate_refdate_not_before(date(2026, 1, 1), date(2026, 1, 1))


def test_validate_refdate_not_before_rejects_earlier_date():
    with pytest.raises(CommandError) as excinfo:
        validate_refdate_not_before(date(2026, 1, 1), date(2026, 1, 2))

    assert excinfo.value.code == "refdate-before-history"


def test_next_number_is_one_when_no_decisions_exist(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    assert next_number(scan_decisions(tmp_path, config)) == 1


def test_next_number_and_unique_title_with_real_decisions(tmp_path):
    config_dict = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=3, title="Existing decision", version=1)
    with open(adr_dir / "ADR003V01-existing-decision.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    decisions = scan_decisions(adr_dir, config)

    assert next_number(decisions) == 4
    assert find_by_unique_title("Existing Decision", config, decisions) is not None
    assert find_by_unique_title("Existing decision", config, decisions) is not None
    assert find_by_unique_title("Totally different", config, decisions) is None


def test_resolve_repo_and_target_reports_when_no_adr_config_is_found_above(tmp_path):
    """Cannot-determine-root-path
    (raised when find_repo_root walks all the way up without finding
    adr-config.adrplus) had zero coverage -- reachable from every one of
    the 6 status-transition commands via resolve_repo_and_target."""
    orphan_dir = tmp_path / "no-repo-here"
    orphan_dir.mkdir()
    target = orphan_dir / "ADR001V01-orphan.md"
    target.write_text("not a real decision", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        resolve_repo_and_target(target)

    assert excinfo.value.code == "cannot-determine-root-path"


def test_resolve_target_and_config_reports_a_missing_directory(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        resolve_target_and_config(tmp_path / "does-not-exist")

    assert excinfo.value.code == "target-directory-not-found"


def test_resolve_target_and_config_reports_a_missing_config(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        resolve_target_and_config(tmp_path)

    assert excinfo.value.code == "config-not-found"


def test_resolve_target_and_config_loads_and_returns_the_config(tmp_path):
    (tmp_path / "adr-config.adrplus").write_bytes(Path(FIXTURE_PATH).read_bytes())

    target, config_path, config = resolve_target_and_config(tmp_path)

    assert target == tmp_path
    assert config_path == tmp_path / "adr-config.adrplus"
    assert config.folderadr == load_repo_config(FIXTURE_PATH).folderadr


def test_resolve_target_and_config_skips_the_config_check_when_not_required(tmp_path):
    """init's own case: a missing config is its normal, expected state,
    not an error -- require_config=False must still enforce the
    directory check, but return without ever looking for the config
    file or loading it."""
    target, config_path, config = resolve_target_and_config(tmp_path, require_config=False)

    assert target == tmp_path
    assert config_path == tmp_path / "adr-config.adrplus"
    assert config is None


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("", "adr-file-empty"),
        ("|only one line|", "adr-file-too-short"),
    ],
)
def test_load_target_surfaces_the_specific_header_error_as_the_code(tmp_path, content, expected_code):
    """Header.error is already a specific, correctly-
    computed reason (adr-file-empty, adr-header-title-not-found, ...);
    load_target discarded it behind a single fixed "header-invalid" code,
    forcing an agent to fall back to a stderr string it can't rely on."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    target = adr_dir / "ADR001V01-broken.md"
    target.write_text(content, encoding="utf-8")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        load_target(target)

    assert excinfo.value.code == expected_code


def test_load_target_reports_no_encoding_repair_for_a_clean_file(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Clean", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-clean.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body\n")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    *_rest, encoding_repaired = load_target(target)

    assert encoding_repaired is False


def test_load_target_reports_encoding_repair_when_the_header_has_invalid_utf8_bytes(tmp_path):
    """Reading a file with invalid UTF-8 bytes WITHIN its 12-line header
    (Fase 4: tolerated, confirmed live to match the reference tool)
    silently replaces them with U+FFFD -- nothing told the caller this
    happened, even though it's a real, permanent loss of the original
    bytes the moment the file is rewritten.

    ADR006V01: load_target/read_target now read ONLY the bounded header
    (never the body) -- invalid bytes WITHIN THE BODY are no longer
    detectable from this call alone; that signal now comes from
    stream_normalized_body_chunks' own `report["encoding_repaired"]` at
    write time, combined by each CLI command with this header-level flag
    (see test_status_transitions.py's own
    test_approve_replaces_invalid_utf8_bytes_in_body_same_as_the_real_tool
    for the end-to-end, body-corruption case)."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Dirty", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-dirty.md"
    header_text = build_header(config, record)
    # Corrupt a byte WITHIN the header itself (inside the title cell),
    # not past it -- the only case load_target's own bounded header read
    # can still see.
    corrupted_header = header_text.encode("utf-8").replace(b"Dirty", b"Dir\xa4ty")
    with open(target, "wb") as handle:
        handle.write(corrupted_header)
        handle.write(b"# body\n")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    *_rest, encoding_repaired = load_target(target)

    assert encoding_repaired is True


_BODY_MATRIX_CASES = [
    b"",
    b"line1",
    b"line1\n",
    b"line1\r\nline2",
    b"line1\n\n\n",
    b"line1\nline2",
    b"\n",
    b"a\r\nb\rc\nd",
    b"line1\ninvalid byte here: \xa4 end\n",
    b"line1\r\ninvalid byte here: \xa4end",
    "línea\n".encode("utf-8") + b"\xa4" + b"more\n",
    b"x" * 5000 + b"\r\n" + b"y" * 5000,
    ("é" * 3000).encode("utf-8"),
    b"a" * 100 + "ééé".encode("utf-8") + b"b" * 100 + b"\r\n" + b"c" * 100,
    b"a" * 50 + b"\xa4" + b"b" * 50,
]


@pytest.mark.parametrize("body_bytes", _BODY_MATRIX_CASES)
def test_stream_normalized_body_chunks_matches_read_body_byte_for_byte(tmp_path, body_bytes):
    """ADR006V01: the streaming replacement must reproduce
    read_body(read_lines_with_report(path))'s own historical output
    byte-for-byte, including its encoding_repaired signal, for every
    line-ending combination and invalid-UTF-8 placement -- verified
    against the STILL-PRESENT, unmodified reference implementation
    (read_lines_with_report + read_body), not a hand-derived
    expectation."""
    from adrpy.core.lifecycle import read_lines_with_report

    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Matrix", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-matrix.md"
    header_text = build_header(config, record)
    with open(target, "wb") as handle:
        handle.write(header_text.encode("utf-8"))
        handle.write(body_bytes)

    lines, expected_repaired = read_lines_with_report(target)
    expected_text = read_body(lines)

    report = {}
    actual_bytes = b"".join(stream_normalized_body_chunks(target, report))

    assert actual_bytes == expected_text.encode("utf-8")
    assert report["encoding_repaired"] is expected_repaired


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 4, 7, 16, 64])
def test_stream_normalized_body_chunks_is_chunk_size_independent(tmp_path, monkeypatch, chunk_size):
    """The straddling-boundary logic (a CRLF or a multi-byte UTF-8
    sequence split across a chunk read) must produce the identical result
    regardless of where the boundary falls -- forced here with
    deliberately tiny chunk sizes to guarantee every case straddles."""
    import adrpy.core.lifecycle as lifecycle_module
    from adrpy.core.lifecycle import read_lines_with_report

    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Straddle", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-straddle.md"
    body_bytes = b"a" * 20 + "ééé".encode("utf-8") + b"b" * 20 + b"\r\n" + b"c" * 20 + b"\xa4" + b"d" * 20
    header_text = build_header(config, record)
    with open(target, "wb") as handle:
        handle.write(header_text.encode("utf-8"))
        handle.write(body_bytes)

    lines, expected_repaired = read_lines_with_report(target)
    expected_text = read_body(lines)

    monkeypatch.setattr(lifecycle_module, "STREAM_CHUNK_SIZE", chunk_size)
    report = {}
    actual_bytes = b"".join(stream_normalized_body_chunks(target, report))

    assert actual_bytes == expected_text.encode("utf-8")
    assert report["encoding_repaired"] is expected_repaired


def test_stream_normalized_body_chunks_does_not_read_the_whole_body_into_memory(tmp_path):
    """Round 28 / ADR006V01's own reason for existing: a 20MB body must
    never be assembled as one in-memory bytes/str object."""
    import tracemalloc

    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Big", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-big.md"
    header_text = build_header(config, record)
    huge_body = (b"line\n") * (4 * 1024 * 1024)  # ~20MB
    with open(target, "wb") as handle:
        handle.write(header_text.encode("utf-8"))
        handle.write(huge_body)

    report = {}
    tracemalloc.start()
    total_bytes = 0
    for chunk in stream_normalized_body_chunks(target, report):
        total_bytes += len(chunk)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # os.linesep may expand each bare '\n' (e.g. to CRLF on Windows) --
    # not a 1:1 byte count, but always within a small constant factor.
    assert len(huge_body) <= total_bytes <= len(huge_body) * 2
    # Peak traced memory stays a small fraction of the ~20MB body --
    # confirms no whole-body buffer, without pinning an exact multiple of
    # the chunk size (regex/decoder scratch overhead is real but bounded).
    assert peak < len(huge_body) / 4


def test_rewrite_status_field_returns_the_write_attempt_count(tmp_path):
    """rewrite_status_field discarded atomic_write_text's
    own attempt count -- callers (approve/reject/undo) had no way to
    surface a "this needed retries" warning."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-existing.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    from adrpy.core.header import parse_header
    from adrpy.core.lifecycle import read_header_lines_with_report
    from adrpy.core.naming import parse_any_filename

    header_lines, _encoding_repaired = read_header_lines_with_report(target)
    header = parse_header(header_lines, config)
    _, filename_info = parse_any_filename(target.name, config)

    from adrpy.core.lock import acquire_repo_lock

    with acquire_repo_lock(adr_dir) as lock:
        _record, _body_encoding_repaired, attempts = rewrite_status_field(
            target, config, header, filename_info, field="update", status="Accepted", refdate=date(2026, 1, 2),
            lock=lock,
        )

    assert attempts == 1


def _header(**overrides):
    defaults = dict(is_valid=True, status_create="Proposed", status_update=None, status_change=None)
    defaults.update(overrides)
    return HeaderParseResult(**defaults)


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": None}, None),
        ({"status_update": "Accepted"}, "already-accepted"),
        ({"status_update": "Rejected"}, "already-rejected"),
        ({"status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted"}, "not-proposed"),
        # A status_update value that is
        # structurally valid (one of the 4 configured status labels, so
        # header.is_valid stays True) but is neither "Accepted" nor
        # "Rejected" -- reachable via a hand-edited/corrupted file whose
        # "Changed" cell contains the "Proposed" or "Superseded" label
        # text. Confirmed against the reference tool's own equivalent check
        # and this project's own pre-refactor boolean (`status_update is
        # None`): BOTH require
        # status_update to be None to be eligible -- any other value,
        # known or not, must be ineligible. The granular-code refactor
        # only excluded "Accepted"/"Rejected" explicitly, silently
        # falling through to eligible for anything else.
        ({"status_update": "Proposed"}, "unexpected-status"),
        ({"status_update": "Superseded"}, "unexpected-status"),
    ],
)
def test_ineligibility_reason_for_approve_or_reject(header_kwargs, expected_reason):
    """Replaces a single collapsed not-eligible-for-* boolean with the
    SPECIFIC observed state -- an agent needs to know
    whether a decision is already accepted, already rejected, or already
    superseded, since each calls for a different recovery action."""
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_approve_or_reject(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": "Rejected"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
    ],
)
def test_ineligibility_reason_for_undo(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_undo(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Rejected"}, "already-rejected"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
        # Same class as approve_or_reject's own
        # case above, but here it's a mislabel rather than a false
        # eligibility -- ineligible either way, but calling a corrupted
        # "Superseded"-in-the-wrong-cell value "already-rejected" is wrong.
        ({"status_update": "Superseded"}, "unexpected-status"),
    ],
)
def test_ineligibility_reason_for_supersede(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_supersede(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": "Rejected"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
        # Mislabel, not a false-eligibility bug
        # here (the boolean outcome already matched) -- but "still-proposed"
        # is wrong for a status_update that isn't actually None.
        ({"status_update": "Superseded"}, "unexpected-status"),
    ],
)
def test_ineligibility_reason_for_version_or_revise(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_version_or_revise(header) == expected_reason


def test_read_header_lines_does_not_read_the_whole_file(tmp_path):
    """Performance backlog item: family_members only ever needs the fixed
    12-line header to decide membership -- reading a potentially huge
    body just for that is wasted I/O, repeated for every sibling on every
    lifecycle check (approve/reject/undo/version/revise/supersede)."""
    header_lines = [f"line{i}" for i in range(12)]
    huge_body = "x" * (5 * 1024 * 1024)
    target = tmp_path / "big.md"
    target.write_text("\n".join(header_lines) + "\n" + huge_body, encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise AssertionError("read_header_lines must not read the whole file")

    with patch.object(Path, "read_text", boom), patch.object(Path, "read_bytes", boom):
        lines = read_header_lines(target, count=12)

    assert lines == header_lines


def test_read_header_lines_handles_a_file_shorter_than_the_header(tmp_path):
    target = tmp_path / "short.md"
    target.write_text("only\ntwo\n", encoding="utf-8")

    lines = read_header_lines(target, count=12)

    assert lines == ["only", "two"]


def test_read_header_lines_with_report_does_not_read_the_whole_file(tmp_path):
    """Same bounded-read guarantee
    as read_header_lines, now also used by migrate's own scan phase."""
    header_lines = [f"line{i}" for i in range(12)]
    huge_body = "x" * (5 * 1024 * 1024)
    target = tmp_path / "big.md"
    target.write_text("\n".join(header_lines) + "\n" + huge_body, encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise AssertionError("read_header_lines_with_report must not read the whole file")

    with patch.object(Path, "read_text", boom), patch.object(Path, "read_bytes", boom):
        lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert lines == header_lines
    assert encoding_repaired is False


def test_read_header_lines_with_report_bounds_total_bytes_read_when_newlines_never_arrive(tmp_path):
    """A round-27 security finding, confirmed live before this fix
    existed: `_read_header_bytes`'s loop re-scanned the ENTIRE
    accumulated buffer for newlines on every 4096-byte chunk (O(n) regex
    work per chunk, O(n^2) total) and grew the buffer via `buffer +=
    more` (O(n) copy per chunk, also O(n^2) total). A file that never
    accumulates `count` real newlines -- a single unstructured blob,
    plausible for corrupted content or a file from an untrusted migrated
    repo -- made the loop run to EOF, so this shared helper (used by
    family_members for every per-file mutating command, AND by
    migrate's own scan phase, AND by explore since round 26) quadratically
    re-scanned and re-copied the file's entire content. Confirmed live:
    1MB=0.6s, 2MB=2.5s, 4MB=10.9s (~4x per doubling). Now bounded to a
    fixed number of chunks regardless of newline count -- a genuine
    header is always a few KB at most (the config schema's own
    field-length limits keep it there), so this cap can never truncate a
    real header, only a pathological one, which then correctly falls
    through to parse_header's own existing adr-file-too-short handling."""
    newline_free_blob = b"x" * (2 * 1024 * 1024)  # 2MB, well past the new cap, zero real newlines
    target = tmp_path / "pathological.md"
    target.write_bytes(newline_free_blob)

    import builtins

    real_open = builtins.open
    total_read = {"bytes": 0}

    def counting_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if str(path) == str(target) and args and "rb" in args:
            real_read = handle.read

            def counting_read(size=-1, *read_args, **read_kwargs):
                data = real_read(size, *read_args, **read_kwargs)
                total_read["bytes"] += len(data)
                return data

            handle.read = counting_read
        return handle

    import time

    start = time.time()
    with patch.object(builtins, "open", counting_open):
        lines, encoding_repaired = read_header_lines_with_report(target, count=12)
    elapsed = time.time() - start

    assert total_read["bytes"] <= 64 * 1024  # generous cap, far below the 2MB blob
    assert elapsed < 1.0  # would take several seconds under the old O(n^2) behavior
    assert len(lines) == 1  # no real newline anywhere in what was actually read


def test_read_header_lines_handles_a_crlf_straddling_a_chunk_boundary(tmp_path):
    """Round 28: _read_header_bytes counted real newlines within each
    freshly-read 4096-byte chunk IN ISOLATION. A `\\r\\n` pair straddling
    exactly on a chunk boundary (the `\\r` as the chunk's own last byte,
    the `\\n` as the next chunk's own first byte) gets counted TWICE by
    two separate isolated per-chunk scans -- once for the lone trailing
    `\\r` in the first chunk's own scan, once more for the lone leading
    `\\n` in the second chunk's own scan -- even though together they are
    exactly ONE real terminator. This double-count can make the loop
    believe it already found `count` real newlines one chunk-read too
    early, stopping before the file's true 12th line is ever read."""
    chunk_size = 4096
    prefix_lines = b"".join(f"L{i}\n".encode() for i in range(9))  # 9 real newlines
    pad = b"x" * (4095 - len(prefix_lines))  # bring the prefix to exactly 4095 bytes
    # byte 4095 = '\r' (chunk 1's own last byte), byte 4096 = '\n' (chunk 2's own
    # first byte) -- terminator #10, straddling the boundary exactly.
    straddling_crlf = b"\r\n"
    # Push well past the chunk-1/chunk-2 boundary before the genuine 12th line,
    # as its own line (terminator #11) -- so a premature stop after chunk 2
    # provably misses the real line 12, without merging into it.
    filler = b"y" * (chunk_size * 2) + b"\n"
    real_line_12 = b"REALLINE12\n"  # terminator #12
    target = tmp_path / "straddle.md"
    target.write_bytes(prefix_lines + pad + straddling_crlf + filler + real_line_12)

    lines = read_header_lines(target, count=12)

    assert len(lines) == 12
    assert lines[11] == "REALLINE12"


def test_read_header_lines_unaffected_by_a_header_within_one_chunk(tmp_path):
    """Positive control: the overwhelmingly common case (a real, schema-
    bounded header, well under one 4096-byte chunk) must be unaffected by
    the boundary fix above."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Small", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-small.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    lines = read_header_lines(target, count=12)

    assert len(lines) == 12


def test_read_header_lines_handles_a_genuine_multi_chunk_header_with_no_straddle(tmp_path):
    """Sanity check: a header that legitimately needs more than one
    4096-byte chunk, with no CRLF anywhere near a chunk boundary, must
    still return the correct 12 lines after the fix."""
    lines_content = [f"line{i}-" + ("z" * 500) for i in range(11)]  # far over one chunk, lone \n only
    target = tmp_path / "multichunk.md"
    target.write_bytes(("\n".join(lines_content) + "\nREALLINE12\n").encode())

    lines = read_header_lines(target, count=12)

    assert len(lines) == 12
    assert lines[11] == "REALLINE12"


def test_read_header_lines_with_report_flags_a_lossy_decode_within_the_header(tmp_path):
    target = tmp_path / "corrupt.md"
    with open(target, "wb") as handle:
        handle.write(b"line0\n")
        handle.write(b"Invalid byte here: \xa4 end.\n")
        handle.write("\n".join(f"line{i}" for i in range(2, 12)).encode("utf-8") + b"\n")

    lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert encoding_repaired is True
    assert "�" in lines[1]


def test_read_header_lines_with_report_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """This read must tolerate a transient PermissionError, matching the
    write side (atomic_write.py) and the lock-file read side
    (core/lock.py's own _read_lock), which both already retry this
    project's own documented Windows "pending delete"/sharing-violation
    contention window -- measured live at ~0.2% of reads under real
    concurrent writers. Same shared helper (core/io_retry.py) `_read_lock`
    already uses, not a fourth independent copy of the loop."""
    target = tmp_path / "flaky.md"
    header_lines = [f"line{i}" for i in range(12)]
    target.write_text("\n".join(header_lines) + "\n", encoding="utf-8")

    import builtins

    real_open = builtins.open
    calls = {"count": 0}

    def flaky_open(path, *args, **kwargs):
        if str(path) == str(target) and "rb" in args:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)

    lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert lines == header_lines
    assert encoding_repaired is False
    assert calls["count"] == 3


def test_read_header_lines_with_report_raises_when_the_permission_error_persists(tmp_path, monkeypatch):
    target = tmp_path / "flaky.md"
    target.write_text("line0\n", encoding="utf-8")

    import builtins

    real_open = builtins.open

    def always_denied(path, *args, **kwargs):
        if str(path) == str(target) and "rb" in args:
            raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", always_denied)

    with pytest.raises(PermissionError):
        read_header_lines_with_report(target, count=12)


def test_read_lines_with_report_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """Same class as the header-read test above, for read_lines_with_report
    (used by read_target's own primary read on every per-file command)."""
    from adrpy.core.lifecycle import read_lines_with_report

    target = tmp_path / "flaky.md"
    target.write_text("body\n", encoding="utf-8")

    real_read_bytes = Path.read_bytes
    calls = {"count": 0}

    def flaky_read_bytes(self, *args, **kwargs):
        if self == target:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    lines, encoding_repaired = read_lines_with_report(target)

    assert lines == ["body"]
    assert encoding_repaired is False
    assert calls["count"] == 3


def test_read_header_lines_with_report_ignores_corruption_far_past_the_header(tmp_path):
    """The bounded read stops once it recovers `count` real lines --
    content genuinely never read is never decoded, so corruption placed
    well past the first read chunk cannot be flagged. (A corrupted byte
    immediately after the header, still inside the same first 4096-byte
    chunk for a small file, WOULD still surface here -- an accepted,
    harmless side effect of the chunk boundary, not a safety gap, since
    migrate's write phase never decodes body bytes either way; they pass
    through raw regardless of what this function reports.)"""
    header_lines = [f"line{i}" for i in range(12)]
    target = tmp_path / "body-corrupt.md"
    with open(target, "wb") as handle:
        handle.write(("\n".join(header_lines) + "\n").encode("utf-8"))
        handle.write(b"x" * 8192)  # push well past the first read chunk
        handle.write(b"\nInvalid byte far into the body: \xa4 end.\n")

    lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert lines == header_lines
    assert encoding_repaired is False


def test_family_members_excludes_a_structurally_invalid_file(tmp_path):
    """family_members must apply
    counts_as_family_member (is_valid OR is_migrated), matching the real
    tool's own equivalent scan -- a filename-matching file whose header
    doesn't parse at all (unmigrated legacy, or simply corrupt) must never
    be counted as a family member, regardless of which naming scheme
    matched its filename."""
    config_dict = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    config_dict["migrationpattern"] = "N00:04T04"
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing decision", version=1, status_create="Proposed")
    with open(adr_dir / "ADR001V01-existing-decision.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    (adr_dir / "0001LegacyNotes.md").write_text("# Not a real header at all\n", encoding="utf-8")

    members = family_members(adr_dir, config, 1)

    assert len(members) == 1
    assert members[0][0].title == "existing-decision"


def test_family_members_fails_closed_when_a_sibling_needs_a_lossy_decode(tmp_path):
    """A round-24 security finding, confirmed live before this fix
    existed: family_members used the no-report header read, so a sibling
    with invalid UTF-8 bytes in its header (e.g. a corrupted or
    hostile-migrated file) silently decoded lossily, failed to parse,
    and was EXCLUDED from the family with zero signal -- not merely
    unwarned about, but invisible to has_superseded_sibling/
    has_pending_sibling, the exact guard every per-file command relies
    on to prevent two live successors (ADR001's own concern). Reproduced
    live end-to-end: a genuinely Superseded V01 with 2 corrupted bytes
    in its status row made `version` on V02 succeed and create a V03,
    duplicating the family, with `warnings: []`. `family_members` can no
    longer trust `existing == []`/a member-list omission to mean
    "genuinely not a member" when the scan that produced it needed a
    lossy decode -- fails closed instead, mirroring migrate's own
    migration-scan-unreliable-encoding for the identical hazard."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing decision", version=1, status_create="Proposed")
    good_path = adr_dir / "ADR001V01-existing-decision.md"
    with open(good_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    raw = good_path.read_bytes()
    corrupted = raw.replace(b"Proposed", b"Prop\xffsed", 1)
    good_path.write_bytes(corrupted)

    with pytest.raises(CommandError) as excinfo:
        family_members(adr_dir, config, 1)

    assert excinfo.value.code == "family-scan-unreliable-encoding"
    assert str(good_path) in excinfo.value.data["unreliable_files"][0]


def test_family_members_exempts_only_the_excluded_path_from_the_encoding_check(tmp_path):
    """`exclude_from_encoding_check` exists specifically for the file every
    real caller is already reading via `read_target` -- that file's own
    encoding reliability is separately surfaced as a warning there, and
    the command's own write is expected to heal it (the same tolerated
    behavior this project has always had for the file actually being
    acted on). Confirmed both directions with the SAME corruption
    shape: excluded, the scan still succeeds and includes the file;
    not excluded (a genuine, unidentified sibling), the exact same
    corruption still fails closed -- this is not a blanket bypass."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing decision", version=1, status_create="Proposed")
    corrupted_path = adr_dir / "ADR001V01-existing-decision.md"
    with open(corrupted_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    raw = corrupted_path.read_bytes()
    corrupted_path.write_bytes(raw.replace(b"Proposed", b"Prop\xffsed", 1))

    members = family_members(adr_dir, config, 1, exclude_from_encoding_check=corrupted_path)

    assert len(members) == 1
    assert members[0][2] == corrupted_path

    with pytest.raises(CommandError) as excinfo:
        family_members(adr_dir, config, 1, exclude_from_encoding_check=adr_dir / "some-other-unrelated-file.md")

    assert excinfo.value.code == "family-scan-unreliable-encoding"


def test_scan_decisions_never_sees_the_lock_marker_file(tmp_path):
    """LOCK_FILE_NAME must never appear as an "unrecognized file" nor be
    mistaken for a naming-scheme candidate.
    Confirmed here as an explicit guarantee, not an accident of every
    rglob call happening to filter on "*.md" -- if that filter ever
    changed, this is the test that would catch a regression."""
    from adrpy.core.lock import LOCK_FILE_NAME

    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    (adr_dir / LOCK_FILE_NAME).write_text("holder-token\n123.0")

    assert scan_decisions(adr_dir, config) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_scan_decisions_ignores_files_reached_through_a_windows_junction(tmp_path):
    """resolve_within only validates the repository
    root; rglob("*.md") happily descends into a Windows junction planted
    inside the decisions folder (no admin privilege required to create
    one, and Path.is_symlink() does NOT detect it). Confirmed live:
    `migrate` wrote a real AdrPlus header into a file OUTSIDE the repo
    through exactly this, and `next_number` was poisoned by the outside
    file's own (unrelated) sequence number."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=9, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR009V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not junction.is_symlink()  # confirms the audit's premise: junctions aren't symlinks

    decisions = scan_decisions(adr_dir, config)

    assert decisions == []
    assert next_number(decisions) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_scan_decisions_reports_an_excluded_candidate_when_given_a_warnings_list(tmp_path):
    """is_within deliberately never
    RAISES over an escaped candidate (a scan should keep going, not fail
    over one), but that's a decision about raising, not about reporting --
    a call site must not drop the exclusion with zero signal, or an agent
    seeing an unexpected next_number, or an inventory that doesn't match
    what's physically listable in the folder, has no way to learn why."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=9, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR009V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    warnings = []
    scan_decisions(adr_dir, config, warnings=warnings)

    assert len(warnings) == 1
    assert "escapes the repository boundary" in warnings[0]
    assert str(junction) in warnings[0]

    # Backward compatible: no warnings= at all (the default) never raises.
    assert scan_decisions(adr_dir, config) == []


def test_scan_decisions_warns_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Path.rglob
    (which scan_decisions uses) silently swallows an OSError raised
    while walking a subtree -- a subfolder that becomes unreadable
    mid-scan must not just make the result set smaller with zero
    signal; every caller that passes warnings= must find out."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    warnings = []
    scan_decisions(adr_dir, config, warnings=warnings)

    assert len(warnings) == 1
    assert "could not be scanned" in warnings[0]
    assert str(blocked) in warnings[0]


def test_scan_decisions_fails_closed_when_strict_and_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Warning alone lets a hidden family member (in an unreadable
    subdirectory) silently defeat safety decisions built on top of this
    scan (family guards, next-number allocation), reproducing a "two
    live successors" corruption with no concurrency needed at all.
    `strict=True` fails closed instead, for callers that need a
    trustworthy result rather than a best-effort listing."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        scan_decisions(adr_dir, config, strict=True, incomplete_code="probe-scan-incomplete")

    assert excinfo.value.code == "probe-scan-incomplete"
    assert str(blocked) in excinfo.value.data["unreadable"][0]


def test_family_members_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Reproduced directly at the source: family_members feeds
    has_superseded_sibling/has_pending_
    sibling/latest_in_family in every per-file command's own family
    guard -- a hidden Superseded/Pending sibling inside an unreadable
    subdirectory must never be silently treated as "no such member"."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        family_members(adr_dir, config, 1)

    assert excinfo.value.code == "family-scan-incomplete"
    # Checks the unreadable list's own contents, not just the code, unlike
    # its sibling tests right above/below -- a mutation corrupting the
    # contents while keeping the code correct would otherwise slip
    # through here.
    assert str(blocked) in excinfo.value.data["unreadable"][0]


def test_reject_folderadr_change_if_decisions_exist_fails_closed_when_scan_incomplete(tmp_path, monkeypatch):
    """Unlike scan_decisions'
    own generic callers (a warning is enough there -- nothing unsafe
    happens from an under-reported inventory), this specific guard
    gates a real safety decision: whether a
    folderadr change is allowed to proceed. If the scan it depends on
    might have silently missed decisions hiding in an unreadable
    subdirectory, `existing == []` can no longer be trusted to mean
    "genuinely empty" -- fails closed instead of allowing an orphaning
    it could not actually rule out."""
    config = load_repo_config(FIXTURE_PATH)
    old_folder = tmp_path / config.folderadr
    old_folder.mkdir(parents=True)
    blocked = old_folder / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        reject_folderadr_change_if_decisions_exist(
            old_folder, config.folderadr, "doc/adrB", config, target=tmp_path, new_config=config
        )

    assert excinfo.value.code == "folderadr-change-scan-incomplete"
    assert excinfo.value.data["folderadr"] == config.folderadr
    assert str(blocked) in excinfo.value.data["unreadable"][0]


def test_reject_folderadr_change_if_decisions_exist_rejects_a_new_folder_that_would_adopt_an_unrelated_file(
    tmp_path,
):
    """A round-22 stability finding: every check above is keyed on the OLD
    folder -- none of them catch the NEW folderadr already containing an
    unrelated pre-existing file that happens to match the naming scheme.
    Confirmed live: pointing folderadr at such a directory silently
    adopted the file as a decision, corrupting the next `new` call's own
    number allocation (ADR008V01 instead of ADR001V01). Same shape hazard
    as --separator's own adoption-check (ADR004V02), just triggered by a
    folder move instead of a naming-rule change."""
    config = load_repo_config(FIXTURE_PATH)
    old_folder = tmp_path / config.folderadr
    old_folder.mkdir(parents=True)

    new_folder = tmp_path / "unrelated-docs"
    new_folder.mkdir(parents=True)
    (new_folder / "ADR001V01-unrelated.md").write_bytes(b"hand written, never a real decision\n")

    with pytest.raises(CommandError) as excinfo:
        reject_folderadr_change_if_decisions_exist(
            old_folder, config.folderadr, "unrelated-docs", config, target=tmp_path, new_config=config
        )

    assert excinfo.value.code == "folderadr-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1
    assert "ADR001V01-unrelated.md" in excinfo.value.data["adopted_files"][0]


def test_reject_folderadr_change_if_decisions_exist_allows_a_new_folder_that_does_not_exist_yet(tmp_path):
    """Companion to the rejection test above: the overwhelmingly common
    case -- pointing folderadr at a brand-new directory nothing has ever
    written to -- must still go through. `find_unreadable_subdirectories`
    treats a nonexistent path as unreadable (confirmed directly), so the
    new-folder check must skip entirely when the new folder does not
    exist yet, the same way `scan_decisions` itself already treats a
    missing folder as empty rather than an error."""
    config = load_repo_config(FIXTURE_PATH)
    old_folder = tmp_path / config.folderadr
    old_folder.mkdir(parents=True)

    reject_folderadr_change_if_decisions_exist(
        old_folder, config.folderadr, "brand-new-folder", config, target=tmp_path, new_config=config
    )  # must not raise


def test_reject_folderadr_change_if_decisions_exist_allows_a_new_folder_with_unrecognized_content(tmp_path):
    """Companion to the rejection test above: a new folder that already
    exists but has nothing that would newly parse as a decision must
    still go through -- this guard must not become a blanket refusal to
    ever repoint folderadr at a non-empty directory."""
    config = load_repo_config(FIXTURE_PATH)
    old_folder = tmp_path / config.folderadr
    old_folder.mkdir(parents=True)

    new_folder = tmp_path / "existing-notes"
    new_folder.mkdir(parents=True)
    (new_folder / "readme.md").write_bytes(b"not decision-shaped at all\n")

    reject_folderadr_change_if_decisions_exist(
        old_folder, config.folderadr, "existing-notes", config, target=tmp_path, new_config=config
    )  # must not raise


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_family_members_forwards_the_warnings_list_to_its_own_scan(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=1, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR001V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    warnings = []
    family_members(adr_dir, config, 1, warnings=warnings)

    assert len(warnings) == 1
    assert "escapes the repository boundary" in warnings[0]


def test_verify_folderadr_unchanged_since_lock_returns_fresh_config_when_matching(tmp_path):
    """The
    lock's own location is derived from a config read taken before the
    lock -- this helper re-reads fresh right after acquiring it and
    confirms folderadr (what the lock's location was derived from)
    didn't drift underneath. The happy path: nothing changed, the fresh
    config is returned for the caller to use from then on."""
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")
    original = load_repo_config(config_path)

    result = verify_folderadr_unchanged_since_lock(config_path, original.folderadr)

    assert result.folderadr == original.folderadr


def test_verify_folderadr_unchanged_since_lock_raises_when_folderadr_changed(tmp_path):
    """Reproduces the class live -- a concurrent
    `config --folderadr` (or `init --seed`) completing between this call's
    own pre-lock bootstrap read and the moment it acquires the lock means
    the lock's own location is no longer the repository's real folderadr.
    Must abort with a structured, mappable error instead of silently
    scanning/writing against a directory the repository no longer uses."""
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["folderadr"] = "doc/adrB"
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        verify_folderadr_unchanged_since_lock(config_path, "doc/adr", warnings=["accumulated"])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}
    assert excinfo.value.warnings == ["accumulated"]


def test_read_body_returns_empty_string_when_there_is_no_body(tmp_path):
    """read_body's `if not
    body_lines: return ""` branch had zero coverage -- config.py's own
    schema documents an empty template as a legitimate, reachable state
    (`config.py`'s `template` field "may be empty"), but every existing
    fidelity test uses a non-empty body."""
    header_only_lines = [f"line{i}" for i in range(12)]

    assert read_body(header_only_lines) == ""


def test_read_body_joins_with_the_host_line_separator(tmp_path):
    header_and_body = [f"line{i}" for i in range(12)] + ["first body line", "second body line"]

    assert read_body(header_and_body) == "first body line" + os.linesep + "second body line" + os.linesep
