import pytest

from adrpy.cli import init, migrate


@pytest.fixture(autouse=True)
def _no_install_level_config_by_default(monkeypatch):
    """`init`/`migrate` both consult the per-user install-level config
    (ADR002V01) by default. Every test in this suite must be
    deterministic regardless of whatever the real machine running them
    happens to have at its own per-user install-config path -- patched
    here, once, for every test, at the name each command module actually
    calls (not core/install_config.py's own name -- `from ... import
    read_install_config_text` binds a separate reference in each of
    those modules' own namespaces, which patching the source module
    would not reach). A test that needs to exercise the install-level
    config path explicitly overrides this with its own monkeypatch.

    Scope, explicitly: this
    covers `init`/`migrate` only -- `installconfig` itself never calls
    `read_install_config_text`, only `resolve_install_config_path`
    directly, which this fixture does NOT patch. `tests/
    test_installconfig.py` isolates that on its own, locally, via its
    own autouse fixture. If a future test anywhere else in this suite
    calls `installconfig.run(...)` directly, it is NOT covered by
    either isolation mechanism and would read/write the real machine's
    own per-user install-config file -- extend one of these two
    fixtures rather than assuming this one already covers it."""
    monkeypatch.setattr(init, "read_install_config_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(migrate, "read_install_config_text", lambda *args, **kwargs: None)


# ---------------------------------------------------------------- make_repo --
# Builds a repository by writing decision files directly (build_header /
# build_filename), without running any command -- for tests of states
# the commands never produce, and of the validator itself.

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from adrpy.core.config import parse_repo_config
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.naming import build_filename

FIXTURE_CONFIG = Path(__file__).parent / "fixtures" / "adr-config.adrplus"
_UNSET = object()
_DAY = date(2026, 1, 1)

# state -> (Created, Changed, Superseded) as the tool writes them.
_STATE_CELLS = {
    "proposed": ("Proposed", None, None),
    "accepted": ("Proposed", "Accepted", None),
    "rejected": ("Proposed", "Rejected", None),
    "superseded": ("Proposed", "Accepted", "Superseded"),
    "placeholder": (None, None, None),
}


@dataclass
class D:
    """One decision file for make_repo. `state` picks the status cells
    (see _STATE_CELLS); `created`/`changed`/`change` override one cell
    each. `successor` is the Superseded cell's reference, `suffix` the
    filename's `--NNN`. `filename` overrides the built name; `content`
    (str or bytes) replaces the whole file, header included."""

    number: int
    version: int = 1
    revision: object = None
    title: object = None
    state: str = "proposed"
    successor: object = None
    suffix: object = None
    migrated: bool = False
    created: object = _UNSET
    changed: object = _UNSET
    change: object = _UNSET
    scope: str = ""
    domain: str = ""
    filename: object = None
    content: object = None
    subdir: str = ""


@dataclass
class Repo:
    root: Path
    config: object
    folder: Path
    paths: list = field(default_factory=list)


def decision_record(config, spec):
    created, changed, change = _STATE_CELLS[spec.state]
    created = created if spec.created is _UNSET else spec.created
    changed = changed if spec.changed is _UNSET else spec.changed
    change = change if spec.change is _UNSET else spec.change
    if spec.migrated and spec.created is _UNSET:
        created = None
    revision = spec.revision
    if revision is None and config.lenrevision > 0:
        revision = 1
    return DecisionRecord(
        number=spec.number,
        title=spec.title if spec.title is not None else f"Decision {spec.number}",
        version=spec.version,
        revision=revision if config.lenrevision > 0 else None,
        scope=spec.scope,
        domain=spec.domain,
        status_create=created,
        date_create=_DAY if created else None,
        status_update=changed,
        date_update=_DAY if changed else None,
        status_change=change,
        date_change=_DAY if change else None,
        superseded_by_file=None if spec.successor is None else f"{spec.successor:0{config.lenseq}d}",
        superseded=spec.suffix,
    )


def make_repo(tmp_path, config=None, files=()):
    """Writes adr-config.adrplus (the test fixture with `config`'s
    fields replacing its own) and each D in `files` under folderadr."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = json.loads(FIXTURE_CONFIG.read_text(encoding="utf-8"))
    data.update(config or {})
    text = json.dumps(data)
    (tmp_path / "adr-config.adrplus").write_text(text, encoding="utf-8")
    parsed = parse_repo_config(text)
    folder = tmp_path / parsed.folderadr
    folder.mkdir(parents=True, exist_ok=True)
    repo = Repo(root=tmp_path, config=parsed, folder=folder)
    for spec in files:
        record = decision_record(parsed, spec)
        name = spec.filename or build_filename(parsed, record)
        directory = folder / spec.subdir if spec.subdir else folder
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        content = spec.content
        if content is None:
            content = build_header(parsed, record, migrated=spec.migrated) + "# body" + "\n"
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        repo.paths.append(path)
    return repo
