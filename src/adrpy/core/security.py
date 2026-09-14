"""Adversarial-input safety checks (harness Fase 5, closed alongside Fase 4,
not after)."""

from pathlib import Path

from adrpy.core.errors import CommandError

_FORBIDDEN_HEADER_FIELD_CHARS = ("|", "\n", "\r")


def resolve_within(base_dir, candidate):
    """Resolves `candidate` (relative or absolute) against `base_dir` and
    rejects it if the real path escapes `base_dir` -- real path resolution
    (following `..` and symlinks), never a string-pattern blacklist."""
    base = Path(base_dir).resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise CommandError("path-outside-repository", f"'{candidate}' resolves outside the repository.")
    return resolved


def reject_embedded_delimiter(value, field_name):
    """A value destined for a fixed-position cell of the header table (a
    free-text field like title/scope/domain) must never contain a character
    that could forge an extra row or break the table -- rejected outright,
    never silently stripped or escaped."""
    if any(char in value for char in _FORBIDDEN_HEADER_FIELD_CHARS):
        raise CommandError(
            "field-contains-forbidden-character",
            f"Field '{field_name}' cannot contain '|' or a line break.",
        )
