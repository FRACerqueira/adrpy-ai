import json
import threading

from adrpy.cli import config, init, new
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError

import pytest


def _init_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    return tmp_path


def test_config_aborts_if_folderadr_changed_after_lock_acquired(tmp_path, monkeypatch):
    """Round 6 stability re-run: config's own comment claimed `current`
    (fresh, inside the lock) and `folder` (this same lock's own
    location) "both are the pre-edit state" -- that invariant didn't
    actually hold. If a concurrent process changes folderadr between
    this call's own bootstrap read (which decides the lock's location)
    and the moment it acquires the lock, this call would lock, scan, and
    validate against a directory the repository no longer uses.
    Simulates the race by returning a stale config from the bootstrap
    read while the file on disk already has the new value."""
    tmp_path = _init_repo(tmp_path)
    stale_bootstrap = load_repo_config(tmp_path / "adr-config.adrplus")

    monkeypatch.setattr(config, "load_repo_config", lambda path: stale_bootstrap)

    data = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    data["folderadr"] = "doc/adrB"
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "XYZ"])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}


def test_config_updates_a_single_field_and_preserves_the_rest(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert result["updated_fields"] == ["prefix"]
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.prefix == "DOC"
    assert after.folderadr == before.folderadr
    assert after.lenseq == before.lenseq
    assert after.activeplugins == before.activeplugins  # untouched, not exposed


def test_config_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """Round 4 test-adequacy audit, Finding 4: retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage."""
    tmp_path = _init_repo(tmp_path)
    real_atomic_write_text = config.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(config, "atomic_write_text", flaky_atomic_write_text)

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert any("3 attempts" in w for w in result["warnings"])


def test_concurrent_config_calls_on_different_fields_do_not_lose_an_update(tmp_path, monkeypatch):
    """Round 4 second corroboration pass (audit-stability, 2/3 and 3/3,
    both independent): config did a read-merge-write with no lock at all
    -- two concurrent calls editing DIFFERENT fields silently lost one of
    the two edits, contradicting this command's own documented contract
    ("an omitted flag preserves the repo's current value, never resets
    it"). Fixed with the same repository lock the other 8 write commands
    already use (scoped to folderadr) -- the second caller simply waits,
    then reads fresh once it acquires the lock, so BOTH edits survive
    instead of either being lost or the second one failing outright."""
    tmp_path = _init_repo(tmp_path)

    from adrpy.cli import config as config_module

    # Widens the read-merge-validate window so both calls are genuinely
    # in flight at once -- with a real lock in place, correctness no
    # longer depends on the exact interleaving (unlike the lock-less
    # code this replaces), so a plain delay (not event-based
    # choreography) is enough here.
    real_parse_repo_config = config_module.parse_repo_config

    def delayed_parse_repo_config(*args, **kwargs):
        import time

        time.sleep(0.05)
        return real_parse_repo_config(*args, **kwargs)

    monkeypatch.setattr(config_module, "parse_repo_config", delayed_parse_repo_config)

    results = [None, None]
    errors = [None, None]
    barrier = threading.Barrier(2)

    def call(index, args):
        barrier.wait()
        try:
            results[index] = config.run(args)
        except Exception as error:  # noqa: BLE001 -- captured for the assertion, not swallowed
            errors[index] = error

    threads = [
        threading.Thread(target=call, args=(0, ["--path", str(tmp_path), "--prefix", "XYZ"])),
        threading.Thread(target=call, args=(1, ["--path", str(tmp_path), "--lenseq", "5"])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == [None, None], f"expected both calls to succeed, got errors: {errors}"
    assert results[0]["updated_fields"] == ["prefix"]
    assert results[1]["updated_fields"] == ["lenseq"]

    final = load_repo_config(tmp_path / "adr-config.adrplus")
    assert final.prefix == "XYZ"
    assert final.lenseq == 5


def test_config_creates_the_decisions_folder_if_missing_before_locking(tmp_path):
    """The repository lock this command now acquires lives inside
    folderadr -- unlike the other 8 write commands, which only ever run
    after `init` already created that directory, nothing requires it to
    exist before `config` runs (e.g. it was deleted, or folderadr was
    just repointed at a fresh path). core.lock._try_create only handles
    FileExistsError, not a FileNotFoundError from a missing parent --
    ensures the directory exists first, matching init's own precedent
    for this identical situation."""
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    import shutil

    shutil.rmtree(adr_dir)
    assert not adr_dir.is_dir()

    result = config.run(["--path", str(tmp_path), "--prefix", "XYZ"])

    assert result["updated_fields"] == ["prefix"]
    assert adr_dir.is_dir()


def test_config_updates_multiple_fields_at_once(tmp_path):
    tmp_path = _init_repo(tmp_path)

    result = config.run(
        ["--path", str(tmp_path), "--folderadr", "decisions", "--separator", "_", "--lenseq", "4"]
    )

    assert set(result["updated_fields"]) == {"folderadr", "separator", "lenseq"}
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == "decisions"
    assert after.separator == "_"
    assert after.lenseq == 4


def test_config_rejects_a_folderadr_change_when_decisions_already_exist(tmp_path):
    """Round 5 stability re-run, Finding 5 (confirmed with the user): a
    folderadr change is only valid when the OLD folder has no recognized
    decisions yet -- otherwise every existing decision becomes invisible
    at its old, still-real path, with nothing telling the caller. A
    structured, mappable error instead of a silent orphaning."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert excinfo.value.code == "folderadr-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"folderadr": "doc/adr", "existing_decisions": 1}
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == before.folderadr  # nothing was written


def test_config_allows_a_folderadr_change_when_no_decisions_exist_yet(tmp_path):
    """Companion to the rejection test above: an empty (or missing)
    decisions folder is exactly the case ADR001's own exemption for init
    already covers -- nothing to orphan, so the change must still go
    through, and the new folder must exist afterward for the next
    command to lock."""
    tmp_path = _init_repo(tmp_path)

    result = config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert result["updated_fields"] == ["folderadr"]
    assert (tmp_path / "decisions").is_dir()


def test_config_does_not_commit_folderadr_if_the_new_folder_cannot_be_created(tmp_path, monkeypatch):
    """Round 7 resilience audit, Finding 3 (retraction of the previous
    mkdir-AFTER-write order): the new folder is now created BEFORE the
    config write commits -- a failure creating it aborts cleanly with
    folderadr still pointing at the OLD, still-real directory, instead of
    committing the change first and leaving the repository pointing at a
    directory that doesn't exist."""
    tmp_path = _init_repo(tmp_path)

    from pathlib import Path as PathType

    real_mkdir = PathType.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if self.name == "newfolder":
            raise PermissionError("Access is denied (simulated)")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "mkdir", failing_mkdir)

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--folderadr", "newfolder"])

    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == "doc/adr"  # unchanged -- nothing committed
    assert not (tmp_path / "newfolder").exists()


def test_config_omitted_fields_keep_current_value(tmp_path):
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    config.run(["--path", str(tmp_path), "--headertitlefile", "Title"])

    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.prefix == "DOC"  # set earlier, preserved by the second call
    assert after.headertitlefile == "Title"


def test_config_toggles_disableplugins(tmp_path):
    tmp_path = _init_repo(tmp_path)

    config.run(["--path", str(tmp_path), "--disableplugins", "true"])
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is True

    config.run(["--path", str(tmp_path), "--disableplugins", "false"])
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is False


def test_config_rejects_invalid_disableplugins_value(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--disableplugins", "maybe"])

    assert excinfo.value.code == "field-not-a-boolean"


@pytest.mark.parametrize("value", ["True", "TRUE", " true ", "False", " FALSE "])
def test_config_normalizes_non_canonical_disableplugins_input(tmp_path, value):
    """Round 4 test-adequacy audit, Finding 9: --disableplugins's own
    `.strip().lower()` normalization had no test with non-canonical input
    (only exactly "true"/"false"/"maybe")."""
    tmp_path = _init_repo(tmp_path)

    config.run(["--path", str(tmp_path), "--disableplugins", value])

    expected = value.strip().lower() == "true"
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is expected


def test_config_rejects_non_integer_lenseq(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "three"])

    assert excinfo.value.code == "field-not-an-integer"


def test_config_still_enforces_schema_bounds(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "99"])

    assert excinfo.value.code == "config-lenseq-too-large"


def test_config_rejects_invalid_merged_value_leaves_file_untouched(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8")

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "~"])

    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == before


def test_config_rejects_folderadr_that_escapes_the_repository(tmp_path):
    """Security audit F7: '../../evil' passes the schema-level relative-
    path check (it has no drive/leading slash) but still escapes the
    repository once resolved -- unlike `init`, which validates this
    before writing, `config` wrote it straight to disk, silently
    bricking the repository (every subsequent command failed with
    path-outside-repository) until someone hand-edited the file back."""
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "../../evil"])

    assert excinfo.value.code == "path-outside-repository"
    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == before


def test_config_with_no_field_flags_reads_the_current_config_without_writing(tmp_path):
    """Usability audit A8 + achado #16 (config.py review): there was no
    way to read the current config through the JSON contract at all (an
    agent needed to know, e.g., whether lenrevision > 0 before calling
    revise, or the current migrationpattern before calling migrate), and
    `config --path X` with no field flags still rewrote (and reformatted)
    the file as a side effect of a call that looks read-only."""
    tmp_path = _init_repo(tmp_path)
    before_bytes = (tmp_path / "adr-config.adrplus").read_bytes()

    result = config.run(["--path", str(tmp_path)])

    assert result["updated_fields"] == []
    assert result["config"]["prefix"] == "ADR"
    assert result["config"]["lenrevision"] == 0
    assert "activeplugins" not in result["config"]
    assert (tmp_path / "adr-config.adrplus").read_bytes() == before_bytes


def test_config_does_not_expose_activeplugins(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(UsageError):
        config.run(["--path", str(tmp_path), "--activeplugins", "Foo"])


def test_config_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path / "missing"), "--prefix", "X"])

    assert excinfo.value.code == "target-directory-not-found"


def test_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "X"])

    assert excinfo.value.code == "config-not-found"


def test_config_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path = _init_repo(tmp_path)

    assert main(["config", "--path", str(tmp_path), "--prefix", "DOC"]) == EXIT_SUCCESS


def test_config_describe_declares_correct_field_types():
    """Usability audit M1: every editable field was declared "string" in
    describe(), including the 3 integer fields and the boolean --
    indistinguishable from a real string field until an agent hit
    field-not-an-integer/field-not-a-boolean by trial and error."""
    arguments = {argument["name"]: argument for argument in config.describe()["arguments"]}

    assert arguments["lenseq"]["type"] == "integer"
    assert arguments["lenversion"]["type"] == "integer"
    assert arguments["lenrevision"]["type"] == "integer"
    assert arguments["disableplugins"]["type"] == "boolean"
    assert arguments["prefix"]["type"] == "string"


def test_config_describe_documents_the_real_domain_constraints():
    """Usability audit M2: every field's description was the tautological
    "New value for '<field>'." -- an agent could only discover a field's
    real domain (separator ∈ {-,_,.}, lenseq ∈ [3,6], prefix max 5
    ASCII letters, ...) by deliberately triggering the corresponding
    config-*-invalid/-too-long error. Descriptions now cite the same
    constants the validator itself enforces, so the two can never drift
    apart silently."""
    from adrpy.core import config as config_schema

    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    for separator in config_schema.VALID_SEPARATORS:
        assert separator in arguments["separator"]
    for transform in config_schema.VALID_CASE_TRANSFORMS:
        assert transform in arguments["casetransform"]
    assert str(config_schema.LENSEQ_MIN) in arguments["lenseq"]
    assert str(config_schema.LENSEQ_MAX) in arguments["lenseq"]
    assert str(config_schema.LENVERSION_MIN) in arguments["lenversion"]
    assert str(config_schema.LENVERSION_MAX) in arguments["lenversion"]
    assert str(config_schema.LENREVISION_MIN) in arguments["lenrevision"]
    assert str(config_schema.LENREVISION_MAX) in arguments["lenrevision"]
    assert str(config_schema.PREFIX_MAX_LENGTH) in arguments["prefix"]
    assert str(config_schema.FOLDERADR_MAX_LENGTH) in arguments["folderadr"]
    assert str(config_schema.HEADER_DISCLAIMER_MAX_LENGTH) in arguments["headerdisclaimer"]
    for field in config_schema._HEADER_LABEL_FIELDS_MAX_40:
        assert str(config_schema.HEADER_LABEL_MAX_LENGTH) in arguments[field]
    for field in config_schema._STATUS_LABEL_FIELDS:
        assert str(config_schema.STATUS_LABEL_MAX_LENGTH) in arguments[field]
    assert "N" in arguments["migrationpattern"] and "T" in arguments["migrationpattern"]
    assert "true" in arguments["disableplugins"] and "false" in arguments["disableplugins"]


def test_config_describe_does_not_falsely_claim_these_three_fields_are_settable_to_empty():
    """Round 5 usability re-run, Finding 3: _field_description advertised
    "may be empty" for migrationpattern/template/prefix, but every
    optional flag goes through parse_flags, which structurally rejects
    an empty string before it ever reaches the field -- this command can
    never actually set any of the three to empty (only `init --seed`
    can). The description must not claim otherwise without qualifying it."""
    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    for field in ("migrationpattern", "template", "prefix"):
        assert "can't set it to an empty string here" in arguments[field]
        assert "init --seed" in arguments[field]


def test_config_describe_documents_the_forbidden_character_constraint():
    """Round 5 usability re-run, Finding 4: these 16 fields all go
    through reject_embedded_delimiter on top of their length bound, but
    none of their descriptions mentioned it -- an agent following only
    the stated domain (any string <= max length, non-empty) could still
    hit config-field-contains-forbidden-character with no prior warning."""
    from adrpy.core import config as config_schema

    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    forbidden_char_fields = config_schema._HEADER_LABEL_FIELDS_MAX_40 + config_schema._STATUS_LABEL_FIELDS + (
        "headerdisclaimer",
    )
    for field in forbidden_char_fields:
        assert "line-break-like character" in arguments[field]


def test_config_describe_documents_the_asymmetric_read_write_json_shape():
    """Round 5 usability re-run, Finding 2: a read result has a `config`
    key; a write result never does (only `updated_fields`) -- a generic
    wrapper that reads `data.config` unconditionally after any `config`
    call would KeyError on a write. Undocumented before this."""
    assert "`config` key" in config.describe()["description"]


def test_field_description_fails_loudly_for_a_field_it_does_not_recognize():
    """Round 4 test-adequacy audit, Finding 10: _field_description's own
    fallback (`return f"New value for '{field}'."`) is unreachable today
    -- every one of the 26 fields in _EDITABLE_FIELDS hits a specific
    branch above it (confirmed by test_config_describe_documents_the_
    real_domain_constraints exercising every field). Silently returning
    that generic, uninformative string for a field none of the branches
    recognize would be the same usability regression M2 already fixed
    (a tautological description an agent can't learn anything from) --
    reintroduced silently the moment a new field is ever added to
    _EDITABLE_FIELDS without a matching branch here. Fails loudly
    instead, so that moment is caught immediately rather than shipped."""
    from adrpy.cli.config import _field_description

    with pytest.raises(AssertionError, match="no-such-field"):
        _field_description("no-such-field")
