"""Maps each CLI verb to its command module (harness Fase 1: one module per command)."""

from adrpy.cli import explore as explore_command
from adrpy.cli import help as help_command
from adrpy.cli import init as init_command
from adrpy.cli import new as new_command

COMMANDS = {
    "help": help_command,
    "init": init_command,
    "explore": explore_command,
    "new": new_command,
}
