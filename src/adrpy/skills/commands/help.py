"""`help` command: lists available adrpy-skills commands, or describes
one of them in full -- mirrors adrpy's own `help` command."""

from adrpy.core.errors import CommandError, FailureCodes, UsageError


def describe():
    return {
        "name": "help",
        "summary": "Lists every adrpy-skills command, or describes one of them in full.",
        "description": (
            "Lists available commands, or describes one command. With no `command` and no --full, "
            "lists every command's name and one-line `summary` only. --full returns every command's "
            "full description and argument list in one call. Naming a specific `command` always "
            "returns its full description and argument list, regardless of --full. Fails with "
            "unknown-command if the named `command` doesn't match any registered command."
        ),
        "arguments": [
            {
                "name": "command",
                "type": "string",
                "required": False,
                "positional": True,
                "description": "Name of the command to describe.",
            },
            {
                "name": "full",
                "type": "switch",
                "required": False,
                "description": (
                    "Return every command's full description and argument list at once, instead of "
                    "the default summarized listing. Ignored when `command` is also given."
                ),
            },
        ],
        "failure_codes": [
            {"code": "usage-error", "condition": "An unrecognized argument, or more than one command name, was given."},
            {"code": "unknown-command", "condition": "The named `command` doesn't match any registered command."},
        ],
    }


def run(args):
    from adrpy.skills.registry import COMMANDS

    full = False
    positional = []
    for token in args:
        if token == "--full":
            full = True
        elif token.startswith("--"):
            raise UsageError(f"Unknown argument: {token}")
        else:
            positional.append(token)
    if len(positional) > 1:
        raise UsageError(f"Unknown argument: {positional[1]}")

    if positional:
        name = positional[0]
        command = COMMANDS.get(name)
        if command is None:
            raise CommandError(FailureCodes.UNKNOWN_COMMAND, f"No such command: {name}")
        return {"commands": [command.describe()]}

    if full:
        return {"commands": [command.describe() for command in COMMANDS.values()]}

    return {
        "commands": [{"name": name, "summary": command.describe()["summary"]} for name, command in COMMANDS.items()],
        "hint": "Run `adrpy-skills help <command>` for one command's full contract, or `adrpy-skills help --full` for every command's.",
    }
