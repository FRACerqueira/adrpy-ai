"""Maps each CLI verb to its command module (harness Fase 1: one module per command)."""

from adrpy.cli import help as help_command

COMMANDS = {
    "help": help_command,
}
