"""Maps each adrpy-skills verb to its command module -- mirrors
adrpy.core.registry, kept as a separate table since adrpy-skills is a
separate entry point from adrpy (ADR009V01)."""

from adrpy.skills.commands import help as help_command
from adrpy.skills.commands import install as install_command
from adrpy.skills.commands import list as list_command
from adrpy.skills.commands import remove as remove_command

COMMANDS = {
    "help": help_command,
    "install": install_command,
    "remove": remove_command,
    "list": list_command,
}
