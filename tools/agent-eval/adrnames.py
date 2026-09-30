"""Decision names as adrpy builds them from a repository's .adrpy.json, so the
harness never hard-codes a naming scheme (prefix, lenseq, lenversion,
lenrevision, separator). Every name a command creates starts at revision 1,
as `new`, `version` and `supersede` do.

Command line, for the shell scripts (REPO is a repository root):
  adrnames.py name REPO NUMBER VERSION SLUG [SUPERSEDED]  -> <folderadr>/<file name>
  adrnames.py label REPO NUMBER                           -> prefix + padded number (ADR0001)
  adrnames.py number REPO NUMBER                          -> padded number (0001)
  adrnames.py revision-cell REPO                          -> the header's Revision value
  adrnames.py normalize REPO < text                       -> text with every decision name made scheme-free
"""
import json
import re
import sys
from pathlib import Path


def load(repo):
    return json.loads((Path(repo) / ".adrpy.json").read_text(encoding="utf-8"))


def number(cfg, n):
    return f"{n:0{cfg['lenseq']}d}"


def label(cfg, n):
    return f"{cfg.get('prefix') or ''}{number(cfg, n)}"


def revision_cell(cfg, revision=1):
    return f"{revision:0{cfg['lenrevision']}d}" if cfg["lenrevision"] > 0 else ""


def name(cfg, n, version, slug, superseded=None, revision=1):
    sep = cfg["separator"]
    revision_part = f"R{revision_cell(cfg, revision)}" if cfg["lenrevision"] > 0 else ""
    suffix = f"{sep}{sep}{number(cfg, superseded)}" if superseded else ""
    return f"{label(cfg, n)}V{version:0{cfg['lenversion']}d}{revision_part}{sep}{slug}{suffix}.md"


def path(cfg, n, version, slug, superseded=None, revision=1):
    return f"{cfg.get('folderadr', 'doc/adr').rstrip('/')}/{name(cfg, n, version, slug, superseded, revision)}"


def name_regex(cfg):
    """Groups: number, version, revision (or None), title, superseded number (or None)."""
    prefix, sep = re.escape(cfg.get("prefix") or ""), re.escape(cfg["separator"])
    return re.compile(rf"^{prefix}(\d+)V(\d+)(?:R(\d+))?{sep}(.+?)(?:{sep}{sep}(\d+))?\.md$", re.I)


def normalize(cfg, text):
    """`ADR0002V01R01-x--0001.md` -> `{2V1}-x--{1}.md`, whatever the widths: the
    control tables then hold what a verdict says, not how names were padded."""
    prefix, sep = re.escape(cfg.get("prefix") or ""), re.escape(cfg["separator"])
    text = re.sub(rf"{sep}{sep}(\d+)\b", lambda m: f"{cfg['separator'] * 2}{{{int(m.group(1))}}}", text)
    return re.sub(rf"\b{prefix}(\d+)V(\d+)(?:R\d+)?", lambda m: f"{{{int(m.group(1))}V{int(m.group(2))}}}", text)


if __name__ == "__main__":
    sys.stdout.reconfigure(newline="\n")  # $(...) strips "\n", never the "\r" Windows adds
    command, repo, *rest = sys.argv[1:]
    cfg = load(repo)
    if command == "name":
        n, version, slug, *superseded = rest
        print(path(cfg, int(n), int(version), slug, int(superseded[0]) if superseded else None))
    elif command == "label":
        print(label(cfg, int(rest[0])))
    elif command == "number":
        print(number(cfg, int(rest[0])))
    elif command == "revision-cell":
        print(revision_cell(cfg))
    elif command == "normalize":
        sys.stdout.write(normalize(cfg, sys.stdin.read()))
    else:
        sys.exit(f"unknown command: {command}")
