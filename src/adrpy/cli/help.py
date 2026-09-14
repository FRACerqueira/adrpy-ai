"""`help` command: lists available commands, or describes one of them."""

from adrpy.core.i18n import translate


def describe():
    return {
        "name": "help",
        "description": translate("help.description"),
        "arguments": [
            {
                "name": "command",
                "type": "string",
                "required": False,
                "description": translate("help.arguments.command.description"),
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
            raise CommandError("unknown-command", translate("help.unknown_command", name=name))
        return {"commands": [command.describe()]}

    return {"commands": [command.describe() for command in COMMANDS.values()]}
