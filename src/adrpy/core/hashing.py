"""Content-hash drift marker shared by adrpy-skills install/remove/list.

A generated file or AGENTS.md block carries a trailing marker comment
recording a hash of everything else in it, so a later install/remove can
tell whether it is still exactly what was last generated before touching
it again -- see ADR009V01.
"""

import hashlib
import re

_MARKER_RE = re.compile(r"<!-- adrpy-skills: v(?P<version>\S+) sha256:(?P<hash>[0-9a-f]{64}) -->\n?")


def compute_hash(content):
    """sha256 hex digest of content, encoded as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_marker(version, content):
    """The marker line for `content` (which must NOT itself already
    contain a marker -- hashing the marker would be circular)."""
    return f"<!-- adrpy-skills: v{version} sha256:{compute_hash(content)} -->"


def parse_marker(text):
    """Returns (version, hash) from the first adrpy-skills marker found in
    text, or None if no marker is present."""
    match = _MARKER_RE.search(text)
    if match is None:
        return None
    return match.group("version"), match.group("hash")


def strip_marker(text):
    """Removes the marker line (and its trailing newline) from text, for
    re-hashing what the marker itself claims to cover."""
    return _MARKER_RE.sub("", text, count=1)


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
