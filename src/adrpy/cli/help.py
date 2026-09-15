"""`help` command: lists available commands, or describes one of them."""


def describe():
    return {
        "name": "help",
        "description": "Lists available commands, or describes one command.",
        "arguments": [
            {
                "name": "command",
                "type": "string",
                "required": False,
                # Usability audit A3: every other command's arguments are
                # `--flag value`, parsed by parse_flags -- this one alone
                # is positional (`help <command>`, no `--`), matching the
                # real tool's own `adrplus help [command]` syntax. Without
                # this flag an agent generalizing from the other 11
                # commands would reasonably (and wrongly) try
                # `help --command X`.
                "positional": True,
                "description": "Name of the command to describe.",
            },
        ],
    }


def run(args):
    from adrpy.core.errors import CommandError
    from adrpy.core.registry import COMMANDS

    if args:
        name = args[0]
        command = COMMANDS.get(name)
        if command is None:
            raise CommandError("unknown-command", f"No such command: {name}")
        return {"commands": [command.describe()]}

    return {"commands": [command.describe() for command in COMMANDS.values()]}
