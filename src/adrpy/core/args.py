"""Shared `--flag value` argument parsing (harness Fase 1): every command's
CLI args follow the same shape, so this is one function, not N near-copies."""

from adrpy.core.errors import UsageError


def parse_flags(args, required=(), optional=(), switches=()):
    """`required`/`optional` are flag names (without `--`) that take a
    value; `switches` are presence-only flags (e.g. `--empty`) that take
    none. Returns a dict keyed by flag name -- switches map to True when
    present, and are simply absent from the dict otherwise. Raises
    UsageError for an unknown flag, a value-flag missing its value, or a
    missing required flag."""
    known_values = set(required) | set(optional)
    known_switches = set(switches)
    values = {}
    i = 0
    while i < len(args):
        token = args[i]
        if not token.startswith("--") or token[2:] not in known_values | known_switches:
            raise UsageError(f"Unknown argument: {token}")
        name = token[2:]
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
