"""Current-scheme filename parsing (harness Fase 7 item 1's digit-overflow
check needs this now). The LEGACY naming scheme is a separate concern,
added in Fase 6 -- a file that doesn't match the current scheme is simply
not counted here yet, a gap to close once the legacy parser exists.

Ported from PatternParser.ParseAdrPattern's regex
(`^([A-Za-z]*)(\\d+)(?:[Vv](\\d+)(?:[Rr](\\d+))?)?$`): number/version/revision
are variable-length digit runs, NOT padded to the *current* config's
lenseq/lenversion/lenrevision -- deliberately so, since the whole point of
this check is to recognize an existing file whose digits no longer fit a
newly-*shrunk* config. Applied to the head of the filename up to its first
separator, mirroring the real split between the "prefix+numbers" segment
and the title.
"""

import re
from dataclasses import dataclass

_ADR_PATTERN = re.compile(r"^([A-Za-z]*)(\d+)(?:[Vv](\d+)(?:[Rr](\d+))?)?$")


@dataclass
class ParsedFileName:
    number: int
    version: int
    revision: int | None


def parse_filename(filename, config):
    if not filename.lower().endswith(".md"):
        return None
    name = filename[:-3]

    index = name.find(config.separator)
    if index < 0:
        return None
    head = name[:index]

    match = _ADR_PATTERN.match(head)
    if match is None:
        return None

    number = int(match.group(2))
    version = int(match.group(3)) if match.group(3) else 0
    revision = int(match.group(4)) if match.group(4) else None

    return ParsedFileName(number=number, version=version, revision=revision)
