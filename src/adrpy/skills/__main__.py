"""Entry point: `adrpy-skills install|remove|list` -- see ADR009V01. A
separate console script from `adrpy` itself; never touches its command
surface or `describe()` contracts."""

import sys

from adrpy.core.errors import UsageError
from adrpy.core.output import EXIT_SUCCESS, emit_failure, emit_success, emit_usage_failure
from adrpy.skills.registry import COMMANDS


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("--help", "-h"):
        argv = ["help", *argv[1:]]

    verb, rest = argv[0], argv[1:]
    command = COMMANDS.get(verb)
    if command is None:
        return emit_usage_failure("unknown-command", f"Unknown command: {verb}")

    try:
        data = command.run(rest)
    except UsageError as error:
        return emit_usage_failure("usage-error", str(error))
    except OSError as error:
        return emit_failure("io-error", str(error))

    return emit_success(data)


if __name__ == "__main__":
    sys.exit(main())
