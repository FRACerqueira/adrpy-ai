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

    Scope, explicitly (round 11 test-adequacy pass, Finding A): this
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
