"""Entry point: dispatches argv to the matching command module."""

import sys

from adrpy.core.errors import CommandError, UsageError
from adrpy.core.i18n import translate
from adrpy.core.output import EXIT_USAGE_ERROR, emit_failure, emit_success
from adrpy.core.registry import COMMANDS


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("--help", "-h"):
        argv = ["help", *argv[1:]]

    verb, rest = argv[0], argv[1:]
    command = COMMANDS.get(verb)
    if command is None:
        print(translate("cli.unknown_verb", verb=verb), file=sys.stderr)
        return EXIT_USAGE_ERROR

    try:
        data = command.run(rest)
    except UsageError as error:
        print(str(error), file=sys.stderr)
        return EXIT_USAGE_ERROR
    except CommandError as error:
        return emit_failure(error.code, error.detail)

    return emit_success(data)


if __name__ == "__main__":
    sys.exit(main())
