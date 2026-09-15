"""Shared lifecycle-transition helpers (harness Fase 7): date-reference
validation and title-uniqueness/next-number resolution, used by
new/approve/reject/undo/supersede/version/revise so each command doesn't
duplicate this logic (Fase 1: one shared function, not copies)."""

from datetime import date as date_cls

from adrpy.core.casing import unique_title_key
from adrpy.core.errors import CommandError
from adrpy.core.naming import parse_any_filename


def validate_refdate_not_in_future(refdate):
    """Mirrors Helper.ValidateRefDateNotInFuture."""
    if refdate > date_cls.today():
        raise CommandError("refdate-in-future", f"Reference date {refdate.isoformat()} is in the future.")


def validate_refdate_not_before(refdate, not_before):
    """Mirrors Helper.ValidateRefDateNotBefore."""
    if refdate < not_before:
        raise CommandError(
            "refdate-before-history",
            f"Reference date {refdate.isoformat()} is before {not_before.isoformat()}.",
        )


def scan_decisions(folder, config):
    """Recognizes BOTH naming schemes (Fase 6 checklist) -- every command
    that resolves "next number" or "does this title already exist" must
    consider legacy files too. Returns a list of (scheme, ParsedFileName,
    path) for every recognized file under `folder`."""
    if not folder.is_dir():
        return []
    found = []
    for candidate in folder.rglob("*.md"):
        result = parse_any_filename(candidate.name, config)
        if result is not None:
            scheme, parsed = result
            found.append((scheme, parsed, candidate))
    return found


def next_number(decisions):
    """Mirrors AdrService.GetNextNumberFrom: 1 if none exist, else max+1."""
    if not decisions:
        return 1
    return max(parsed.number for _, parsed, _ in decisions) + 1


def find_by_unique_title(title, config, decisions):
    """Mirrors AdrService.GetFileByUniqueTitleFrom. Returns the matching
    Path, or None."""
    key = unique_title_key(title, config)
    for _, parsed, path in decisions:
        if parsed.title is not None and unique_title_key(parsed.title, config) == key:
            return path
    return None
