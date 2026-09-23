"""Content-hash drift marker shared by adrpy-skills install/remove/list.

A generated file or AGENTS.md block carries a leading marker comment
recording a hash of everything else in it, so a later install/remove can
tell whether it is still exactly what was last generated before touching
it again -- see ADR009V01.
"""

import hashlib
import re

# Anchored to where `_insert_marker` (installer.py) places the real marker:
# position 0, or immediately after a leading `---\n...\n---\n` frontmatter
# block, never anywhere else -- an unanchored search would read a foreign
# file with a marker-shaped comment embedded mid-body as "clean"/
# "drifted". Frontmatter is matched on its own first, up to its FIRST
# closing `---` (the same boundary installer.py's _FRONTMATTER_RE uses to
# insert the marker): a single regex with an optional lazy frontmatter
# group backtracks past that boundary, over later `---` rule lines, to
# reach a marker-shaped comment further down the body.
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_MARKER_RE = re.compile(r"<!-- adrpy-skills: v(?P<version>\S+) sha256:(?P<hash>[0-9a-f]{64}) -->\n?")


def _leading_marker(text):
    """(frontmatter, marker match) for the marker at its one legitimate
    position, or (frontmatter, None) when there is no marker there."""
    frontmatter = _FRONTMATTER_RE.match(text)
    position = frontmatter.end() if frontmatter else 0
    return (frontmatter.group(0) if frontmatter else ""), _MARKER_RE.match(text, position)


def compute_hash(content):
    """sha256 hex digest of content, encoded as UTF-8. Canonicalizes
    newlines to bare "\\n" first (any "\\r\\n" or lone "\\r" collapses to
    "\\n") -- Round 37, Class P6: `content` is hashed before
    atomic_write_text's own newline normalization (to the host's
    os.linesep) ever runs, so without this the hash would depend on
    whatever newline convention `content` happened to arrive in, not on
    the bytes actually written to disk. Canonicalizing here, on both the
    write side (via build_marker) and the read side (via check_drift),
    keeps the two in agreement regardless of host OS or input
    convention."""
    canonical = content.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_marker(version, content):
    """The marker line for `content` (which must NOT itself already
    contain a marker -- hashing the marker would be circular)."""
    return f"<!-- adrpy-skills: v{version} sha256:{compute_hash(content)} -->"


def parse_marker(text):
    """Returns (version, hash) from the marker at the position
    `_insert_marker` would have placed it (position 0, or immediately
    after a leading frontmatter block), or None if no marker is there --
    never a marker-shaped substring anywhere else in `text`."""
    _frontmatter, match = _leading_marker(text)
    if match is None:
        return None
    return match.group("version"), match.group("hash")


def strip_marker(text):
    """Removes the marker line (and its trailing newline) from text, for
    re-hashing what the marker itself claims to cover -- keeping any
    leading frontmatter block intact, since that was part of what
    `build_marker` originally hashed (the marker sits AFTER frontmatter,
    never replacing it). Only ever strips a marker at its one legitimate
    position (see _leading_marker) -- never a marker-shaped substring
    found later in the text."""
    frontmatter, match = _leading_marker(text)
    if match is None:
        return text
    return frontmatter + text[match.end() :]


def check_drift(existing_text):
    """existing_text is the current real content at a target path or
    AGENTS.md block (or None if nothing exists there yet). Returns one of:

    - "absent"  -- nothing there yet; safe to write.
    - "foreign" -- something exists with no adrpy-skills marker at all --
                   a naming collision, or hand-written content.
    - "clean"   -- a marker exists and the surrounding content still
                   hashes to what it recorded -- safe to overwrite.
    - "drifted" -- a marker exists, but the surrounding content no longer
                   hashes to what it recorded -- hand-edited since it was
                   generated.
    """
    if existing_text is None:
        return "absent"
    marker = parse_marker(existing_text)
    if marker is None:
        return "foreign"
    _, recorded_hash = marker
    actual_hash = compute_hash(strip_marker(existing_text))
    return "clean" if actual_hash == recorded_hash else "drifted"
