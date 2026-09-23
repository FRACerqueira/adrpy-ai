"""Entry point: `adrpy-skills install|remove|list` -- see ADR009V01. A
separate console script from `adrpy` itself; never touches its command
surface or `describe()` contracts."""

import sys
from importlib.metadata import PackageNotFoundError, metadata

from adrpy.core.errors import CommandError, UsageError
from adrpy.core.output import EXIT_SUCCESS, emit_failure, explain, emit_success, emit_usage_failure
from adrpy.skills.registry import COMMANDS

_FALLBACK_SUMMARY = "Multi-provider AI-coding-agent skills installer for adrpy-ai."


def _print_version():
    # The one deliberate exception to "every response is a single JSON
    # object on stdout" -- mirrors adrpy/__main__.py's own _print_version.
    try:
        info = metadata("adrpy-ai")
        version, summary = info["Version"], _FALLBACK_SUMMARY
    except PackageNotFoundError:
        version, summary = "unknown (not installed)", _FALLBACK_SUMMARY
    print(f"adrpy-skills {version}")
    print(summary)
    print()
    print("Usage: adrpy-skills help")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] in ("--version", "-v"):
        _print_version()
        return EXIT_SUCCESS

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
    except CommandError as error:
        return emit_failure(error.code, error.detail, error.data, error.warnings)
    except OSError as error:
        return emit_failure("io-error", explain(error))
    except KeyboardInterrupt:
        # Same gap, same fix as adrpy/__main__.py's own -- KeyboardInterrupt
        # is a BaseException, not an Exception, so the catch-all below never
        # sees it. Found by a Round 37 test-adequacy pass specifically
        # because this sibling entry point never got the core fix applied.
        return emit_failure("interrupted", "Interrupted (Ctrl+C).")
    except Exception as error:  # noqa: BLE001 -- last-resort contract guard, see adrpy/__main__.py
        return emit_failure("internal-error", explain(error))

    return emit_success(data)


if __name__ == "__main__":
    sys.exit(main())
