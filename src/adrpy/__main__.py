"""Entry point: dispatches argv to the matching command module."""

import sys

from adrpy.core.errors import CommandError, UsageError
from adrpy.core.i18n import translate
from adrpy.core.output import emit_failure, emit_success, emit_usage_failure
from adrpy.core.registry import COMMANDS


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("--help", "-h"):
        argv = ["help", *argv[1:]]

    verb, rest = argv[0], argv[1:]
    command = COMMANDS.get(verb)
    if command is None:
        return emit_usage_failure("unknown-command", translate("cli.unknown_verb", verb=verb))

    try:
        data = command.run(rest)
    except UsageError as error:
        return emit_usage_failure("usage-error", str(error))
    except CommandError as error:
        return emit_failure(error.code, error.detail, error.data)
    except OSError as error:
        # Fidelity/resilience/usability audits (independently, 3 fronts):
        # any OSError not already translated into a CommandError by the
        # command itself (a permission failure, a full disk, a missing
        # parent directory) used to propagate as a raw traceback with
        # EMPTY stdout -- breaking the JSON contract this whole project
        # exists to provide, at exactly the moment an agent needs it most.
        return emit_failure("io-error", str(error))
    except Exception as error:  # noqa: BLE001 -- last-resort contract guard, see above
        return emit_failure("internal-error", str(error))

    return emit_success(data)


if __name__ == "__main__":
    sys.exit(main())
