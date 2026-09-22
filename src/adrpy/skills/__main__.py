"""Entry point: `adrpy-skills install|remove|list` -- see ADR009V01. A
separate console script from `adrpy` itself; never touches its command
surface or `describe()` contracts."""

import sys

from adrpy.core.args import parse_flags
from adrpy.core.errors import UsageError
from adrpy.core.output import EXIT_SUCCESS, emit_failure, emit_success, emit_usage_failure
from adrpy.skills import installer


def _split(value):
    if value is None:
        return ["all"]
    return [v.strip() for v in value.split(",") if v.strip()]


def _run_install(args):
    flags = parse_flags(args, optional=("provider", "target", "path", "skill"), switches=("force",))
    return installer.install(
        target_dir=flags.get("path", "."),
        providers=_split(flags.get("provider")),
        skills=_split(flags.get("skill")),
        scope=flags.get("target", "project"),
        force=flags.get("force", False),
    )


def _run_remove(args):
    flags = parse_flags(args, optional=("provider", "target", "path", "skill"), switches=("force",))
    return installer.remove(
        target_dir=flags.get("path", "."),
        providers=_split(flags.get("provider")),
        skills=_split(flags.get("skill")),
        scope=flags.get("target", "project"),
        force=flags.get("force", False),
    )


def _run_list(args):
    flags = parse_flags(args, optional=("provider", "path", "skill"))
    return installer.list_installed(
        target_dir=flags.get("path", "."),
        providers=_split(flags.get("provider")),
        skills=_split(flags.get("skill")),
    )


_VERBS = {"install": _run_install, "remove": _run_remove, "list": _run_list}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("--help", "-h"):
        print("Usage: adrpy-skills <install|remove|list> [--provider ...] [--skill ...] [--path .] [--target project|global] [--force]")
        return EXIT_SUCCESS

    verb, rest = argv[0], argv[1:]
    handler = _VERBS.get(verb)
    if handler is None:
        return emit_usage_failure("unknown-command", f"Unknown command: {verb}")

    try:
        data = handler(rest)
    except UsageError as error:
        return emit_usage_failure("usage-error", str(error))
    except OSError as error:
        return emit_failure("io-error", str(error))

    return emit_success(data)


if __name__ == "__main__":
    sys.exit(main())
