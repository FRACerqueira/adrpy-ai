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
                # Every other command's arguments are `--flag value`,
                # parsed by parse_flags -- this one alone is positional
                # (`help <command>`, no `--`), a deliberate choice matching
                # the reference tool's own equivalent command. Without this
                # note an agent generalizing from the other commands would
                # reasonably (and wrongly) try `help --command X`.
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
        return {"commands": [command.describe()], "warnings": []}

    # Same reasoning as explore's own "warnings" key -- present
    # unconditionally across every other command's result, even when
    # empty, so a generic wrapper doesn't need a special case for the two
    # read-only commands.
    return {"commands": [command.describe() for command in COMMANDS.values()], "warnings": []}
