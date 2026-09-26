"""`help` command: lists available commands, or describes one of them."""

from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import FailureCodes, build_failure_codes

_DEFAULTS_PREVIEW_FIELDS = (
    "folderadr",
    "prefix",
    "separator",
    "casetransform",
    "lenseq",
    "lenversion",
    "lenrevision",
    "statusnew",
    "statusacc",
    "statusrej",
    "statussup",
)


def describe():
    return {
        "name": "help",
        "summary": "Lists every command, or describes one of them in full.",
        "description": (
            "Lists every command with its one-line summary, plus `defaults` (a short preview of the config a "
            "fresh `init` on this machine would produce, with its `source`) and a `hint`. Naming a `command`,"
            " or passing --full, returns the full contract (description, arguments, failure_codes) instead. "
            "Only the bare listing reads this machine's install-level config, so only it can fail on an "
            "invalid or unreadable one."
        ),
        "arguments": [
            {
                "name": "command",
                "type": "string",
                "required": False,
                # Every other command's arguments are `--flag value`,
                # parsed by parse_flags -- this one alone is positional
                # (`help <command>`, no `--`), the same shape as AdrPlus's
                # equivalent command. Without this
                # note an agent generalizing from the other commands would
                # reasonably (and wrongly) try `help --command X`.
                "positional": True,
                "description": "Name of the command to describe. Positional, unlike every other command's flags: `adrpy help new`, never `adrpy help --command new` (which fails).",
            },
            {
                "name": "full",
                "type": "switch",
                "required": False,
                "description": (
                    "Return every command's full description and argument list at once, instead of "
                    "the default summarized listing. Ignored when `command` is also given -- a single "
                    "named command is already returned in full either way."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.UNKNOWN_COMMAND: "The named `command` doesn't match any registered command.",
                FailureCodes.IO_ERROR: "The bare listing could not read this machine's install-level config (permission denied or similar).",
            },
            CONFIG_FAILURE_CODES,
        ),
    }


def run(args):
    from adrpy.core.errors import FailureCodes, UsageError
    from adrpy.core.registry import COMMANDS

    full = False
    positional = []
    for token in args:
        if token == "--full":
            full = True
        elif token.startswith("-"):
            raise UsageError(f"Unknown argument: {token}", unknown=token)
        else:
            positional.append(token)
    if len(positional) > 1:
        raise UsageError(f"Unknown argument: {positional[1]}")

    if positional:
        name = positional[0]
        command = COMMANDS.get(name)
        if command is None:
            raise UsageError(f"No such command: {name} (see `adrpy help` for the list).", code=FailureCodes.UNKNOWN_COMMAND)
        return {"commands": [command.describe()], "warnings": []}

    if full:
        # Same reasoning as explore's own "warnings" key -- present
        # unconditionally across every other command's result, even when
        # empty, so a generic wrapper doesn't need a special case for the
        # two read-only commands.
        return {"commands": [command.describe() for command in COMMANDS.values()], "warnings": []}

    return {
        "commands": [
            {"name": name, "summary": command.describe()["summary"]} for name, command in COMMANDS.items()
        ],
        "defaults": _defaults_preview(),
        "hint": (
            "Run `adrpy help <command>` for one command's full contract, or `adrpy help --full` for "
            "every command's full contract at once."
        ),
        "warnings": [],
    }


def _defaults_preview():
    from adrpy.core.config import parse_repo_config
    from adrpy.core.install_config import resolve_effective_default_config_text

    source, text = resolve_effective_default_config_text()
    config = parse_repo_config(text)
    preview = {"source": source}
    preview.update({field: getattr(config, field) for field in _DEFAULTS_PREVIEW_FIELDS})
    return preview
