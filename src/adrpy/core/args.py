"""Shared `--flag value` argument parsing: every command's CLI args follow
the same shape, so this is one function, not N near-copies."""

import re

from adrpy.core.errors import UsageError


def plain_int(text):
    """int() for a flag value, taking only ASCII digits with an optional
    leading '-' (surrounding spaces allowed). Plain int() also accepts other
    scripts' digits, '+4' and '4_0'; raises ValueError for those too."""
    stripped = text.strip()
    if not re.fullmatch(r"-?[0-9]+", stripped):
        raise ValueError(f"not a plain integer: {text!r}")
    return int(stripped)


def _names_a_flag(token, known, aliases):
    if token.startswith("--"):
        return token[2:] in known
    return len(token) == 2 and token[1] in aliases


def parse_flags(args, required=(), optional=(), switches=(), aliases=None):
    """`required`/`optional` are flag names (without `--`) that take a
    value; `switches` are presence-only flags (e.g. `--empty`) that take
    none. `aliases` maps a single-letter short form (without `-`, e.g.
    "p") to the long flag name it stands for (e.g. "path") -- `-p value`
    is then exactly equivalent to `--path value`. Returns a dict keyed
    by the LONG flag name --
    switches map to True when present, and are simply absent from the
    dict otherwise. Raises UsageError for an unknown flag, a value-flag
    missing its value or given an empty one (or another of this command's
    own flags in its place), a flag given more than once, or a missing
    required flag.
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
        if name in values:
            # Silently letting the last one win hides a mistyped command.
            raise UsageError(f"--{name} was given more than once")
        i += 1
        if name in known_switches:
            values[name] = True
            continue
        if i >= len(args):
            raise UsageError(f"--{name} requires a value")
        value = args[i]
        if value.startswith("-") and _names_a_flag(value, known_values | known_switches, aliases):
            # `-p --path x`: the value was left out, and the next flag was
            # swallowed as if it were one.
            raise UsageError(f"--{name} requires a value (got the flag {value})")
        if value == "":
            # An empty string is treated the same as an omitted value,
            # not as a real (if unusual) one, matching the reference tool's own
            # confirmed behavior.
            raise UsageError(f"--{name} requires a non-empty value")
        values[name] = value
        i += 1

    missing = [name for name in required if name not in values]
    if missing:
        raise UsageError(f"Missing required argument(s): {', '.join(f'--{m}' for m in missing)}")
    return values
