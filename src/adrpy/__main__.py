"""Entry point: dispatches argv to the matching command module."""

import sys
from importlib.metadata import PackageNotFoundError, metadata

from adrpy.core.errors import CommandError, UsageError
from adrpy.core.output import EXIT_SUCCESS, emit_failure, explain, emit_success, emit_usage_failure
from adrpy.core.registry import COMMANDS

_DOCS_URL = "https://github.com/FRACerqueira/adrpy-ai#readme"
_DECISION_LOG_WORKFLOW_URL = "https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/decision-log-workflow.md"
_FALLBACK_SUMMARY = (
    "ADR lifecycle CLI for humans and AI agents alike -- JSON-only, no wizard, zero dependencies."
)


def _print_version():
    # The one deliberate exception to "every response is a single JSON
    # object on stdout": --version/-v is a human-only convenience never
    # parsed by a script or agent, the same convention every other
    # JSON-first CLI (jq, kubectl, docker) already follows for this
    # exact flag.
    try:
        info = metadata("adrpy-ai")
        version, summary = info["Version"], info["Summary"]
    except PackageNotFoundError:
        # Not installed (e.g. run directly from a source checkout) --
        # still answer instead of crashing on the one flag someone
        # reaches for first after getting the tool onto their machine.
        version, summary = "unknown (not installed)", _FALLBACK_SUMMARY
    print(f"adrpy-ai {version}")
    print(summary)
    print()
    print(f"Docs: {_DOCS_URL}")
    print(f"Decision-log workflow: {_DECISION_LOG_WORKFLOW_URL}")
    print("Usage: adrpy help")


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
        # Any OSError not already translated into a CommandError by the
        # command itself (a permission failure, a full disk, a missing
        # parent directory) would otherwise propagate as a raw traceback
        # with EMPTY stdout -- breaking the JSON contract this whole
        # project exists to provide, at exactly the moment an agent needs
        # it most.
        return emit_failure("io-error", explain(error))
    except KeyboardInterrupt:
        # A signal-driven interrupt (Ctrl+C) is a BaseException, not an
        # Exception -- the catch-all below never sees it, so without this
        # it propagates raw, with EMPTY stdout, the exact failure mode
        # this project exists to prevent. The write layer
        # (core/atomic_write.py) is already hardened specifically against
        # this exception type (it cleans up its own temp file on any
        # BaseException, not just OSError); this closes the same class of
        # gap at the one place that's supposed to guarantee every
        # invocation still ends in valid JSON, not just the write itself.
        return emit_failure("interrupted", "Interrupted (Ctrl+C).")
    except Exception as error:  # noqa: BLE001 -- last-resort contract guard, see above
        return emit_failure("internal-error", explain(error))

    return emit_success(data)


if __name__ == "__main__":
    sys.exit(main())
