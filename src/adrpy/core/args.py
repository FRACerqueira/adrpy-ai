"""Shared `--flag value` argument parsing (harness Fase 1): every command's
CLI args follow the same shape, so this is one function, not N near-copies."""

from adrpy.core.errors import UsageError


def parse_flags(args, required=(), optional=()):
    """`required`/`optional` are flag names without the leading `--`.
    Returns a dict keyed by flag name (only for flags actually supplied).
    Raises UsageError for an unknown flag, a flag missing its value, or a
    missing required flag."""
    known = set(required) | set(optional)
    values = {}
    i = 0
    while i < len(args):
        token = args[i]
        if not token.startswith("--") or token[2:] not in known:
            raise UsageError(f"Unknown argument: {token}")
        name = token[2:]
        i += 1
        if i >= len(args):
            raise UsageError(f"--{name} requires a value")
        values[name] = args[i]
        i += 1

    missing = [name for name in required if name not in values]
    if missing:
        raise UsageError(f"Missing required argument(s): {', '.join(f'--{m}' for m in missing)}")
    return values
