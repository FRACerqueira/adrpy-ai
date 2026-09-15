"""Shared `--flag value` argument parsing (harness Fase 1): every command's
CLI args follow the same shape, so this is one function, not N near-copies."""

from adrpy.core.errors import UsageError


def parse_flags(args, required=(), optional=(), switches=(), aliases=None):
    """`required`/`optional` are flag names (without `--`) that take a
    value; `switches` are presence-only flags (e.g. `--empty`) that take
    none. `aliases` (Fase 7/fidelity audit F10) maps a single-letter short
    form (without `-`, e.g. "p") to the long flag name it stands for
    (e.g. "path") -- `-p value` is then exactly equivalent to
    `--path value`, matching the real adrplus's own short-alias-per-
    argument convention. Returns a dict keyed by the LONG flag name --
    switches map to True when present, and are simply absent from the
    dict otherwise. Raises UsageError for an unknown flag, a value-flag
    missing its value or given an empty one, or a missing required flag.
    """
    known_values = set(required) | set(optional)
    known_switches = set(switches)
    aliases = aliases or {}
    values = {}
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            name = token[2:]
        elif len(token) == 2 and token[0] == "-" and token[1] in aliases:
            name = aliases[token[1]]
        else:
            raise UsageError(f"Unknown argument: {token}")
        if name not in known_values | known_switches:
            raise UsageError(f"Unknown argument: {token}")
        i += 1
        if name in known_switches:
            values[name] = True
            continue
        if i >= len(args):
            raise UsageError(f"--{name} requires a value")
        value = args[i]
        if value == "":
            # Fidelity audit F5: confirmed live, `adrplus --title ""`
            # refuses with "Missing value for argument" -- the real tool
            # treats an empty string the same as an omitted value, not as
            # a real (if unusual) one.
            raise UsageError(f"--{name} requires a non-empty value")
        values[name] = value
        i += 1

    missing = [name for name in required if name not in values]
    if missing:
        raise UsageError(f"Missing required argument(s): {', '.join(f'--{m}' for m in missing)}")
    return values
