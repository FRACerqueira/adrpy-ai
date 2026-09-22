"""Content-hash drift marker shared by adrpy-skills install/remove/list.

A generated file or AGENTS.md block carries a leading marker comment
recording a hash of everything else in it, so a later install/remove can
tell whether it is still exactly what was last generated before touching
it again -- see ADR009V01.
"""

import hashlib
import re

# Anchored to \A, with an optional leading frontmatter block, instead of
# matching anywhere in the text: `_insert_marker` (installer.py) only ever
# places the real marker at position 0, or immediately after a leading
# `---\n...\n---\n` block -- never anywhere else. Round 37, Class P6: an
# unanchored `.search()` would find the FIRST marker-shaped substring
# anywhere in the text, which for a "foreign" file that happens to
# contain one embedded mid-body (hand-written, or copy-pasted from a
# generated file) would misreport it as "clean"/"drifted" instead of
# "foreign".
_MARKER_RE = re.compile(
    r"\A(?P<frontmatter>---\n.*?\n---\n)?<!-- adrpy-skills: v(?P<version>\S+) sha256:(?P<hash>[0-9a-f]{64}) -->\n?",
    re.DOTALL,
)


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
    match = _MARKER_RE.match(text)
    if match is None:
        return None
    return match.group("version"), match.group("hash")


def strip_marker(text):
    """Removes the marker line (and its trailing newline) from text, for
    re-hashing what the marker itself claims to cover -- keeping any
    leading frontmatter block intact, since that was part of what
    `build_marker` originally hashed (the marker sits AFTER frontmatter,
    never replacing it). `_MARKER_RE` is \\A-anchored, so this only ever
    strips a match at the very start of `text` (or right after a leading
    frontmatter block) -- it can never remove a marker-shaped substring
    found later in the text."""
    match = _MARKER_RE.match(text)
    if match is None:
        return text
    return (match.group("frontmatter") or "") + text[match.end() :]


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
