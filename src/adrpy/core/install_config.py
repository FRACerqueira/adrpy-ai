"""Install-level config (ADR002V01): a per-user file holding the full
repo-config schema, used to seed `init` and as a `migrationpattern`
fallback for `migrate` when the repository's own is empty. Deliberately
NOT stored relative to this package's own installation directory (see
the ADR) -- writing into a pip package's own install/site-packages
directory is unsafe (permissions, wiped on reinstall, often shared).

Reuses core/config.py's own schema and validation directly -- the
install-level file's shape is identical to a repository's own
adr-config.adrplus, so there is no separate schema to maintain here.
"""

import os
from pathlib import Path

from adrpy.core.config import parse_repo_config, read_config_text

_APP_DIR_NAME = "adrpy"
_FILE_NAME = "install-config.json"


def resolve_install_config_path():
    """Resolves the per-user install-level config file's path. Never
    checks whether it exists -- callers decide what "doesn't exist yet"
    means for them (the normal state for a fresh installation, per
    ADR002V01, not an error condition)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / _APP_DIR_NAME / _FILE_NAME


def read_install_config_text(path=None):
    """Returns the install-level config's raw text, validated against
    the same schema as a repository's own adr-config.adrplus, or None if
    the file doesn't exist -- the normal state for any installation that
    has never run `installconfig` (ADR002V01), not an error condition.
    Shared by every consumer of this file (`init`'s default seed,
    `migrate`'s migrationpattern fallback) so "does it exist, and is it
    valid" is answered identically everywhere, not reimplemented per
    caller."""
    target = path or resolve_install_config_path()
    if not target.is_file():
        return None
    text = read_config_text(target)
    parse_repo_config(text)  # validates; raises CommandError on corruption
    return text
