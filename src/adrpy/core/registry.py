"""Maps each CLI verb to its command module (one module per command)."""

from adrpy.cli import approve as approve_command
from adrpy.cli import check as check_command
from adrpy.cli import config as config_command
from adrpy.cli import explore as explore_command
from adrpy.cli import help as help_command
from adrpy.cli import init as init_command
from adrpy.cli import installconfig as installconfig_command
from adrpy.cli import log as log_command
from adrpy.cli import migrate as migrate_command
from adrpy.cli import new as new_command
from adrpy.cli import reject as reject_command
from adrpy.cli import revise as revise_command
from adrpy.cli import supersede as supersede_command
from adrpy.cli import undo as undo_command
from adrpy.cli import version as version_command

COMMANDS = {
    "help": help_command,
    "init": init_command,
    "explore": explore_command,
    "check": check_command,
    "new": new_command,
    "approve": approve_command,
    "reject": reject_command,
    "undo": undo_command,
    "supersede": supersede_command,
    "version": version_command,
    "revise": revise_command,
    "migrate": migrate_command,
    "config": config_command,
    "installconfig": installconfig_command,
    "log": log_command,
}
