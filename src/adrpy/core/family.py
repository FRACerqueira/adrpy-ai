"""The family rules shared by the lifecycle commands and the
repository validator: which filename names a successor, and which
member of a family is the live one."""


def is_successor(parsed):
    """True when a filename names a successor: it carries a supersede
    suffix (--NNN) and its own number is higher than the one it names.
    A suffix pointing at its own number or a later one is not a successor
    for any rule (a successor always gets a later number)."""
    return parsed.superseded_from is not None and parsed.number > parsed.superseded_from


def locking_member(filename_info, members):
    """The family member that makes `filename_info`'s decision no longer
    the live one, or None when it is.

    Only the family's latest member is alive. A newer version locks every
    member of an older version, and a newer revision locks the older
    revisions of the same version -- unless every newer one is Rejected:
    rejected attempts never lock what came before them (Round 40; widened
    from "a single Rejected member" in Round 41, both decided by the
    project owner). Membership and
    status come from `members` (headers that parse); version and revision
    from the filename."""

    def blocker(newer):
        if not newer:
            return None
        live = [member for member in newer if member[1].status_update != "Rejected"]
        if not live:
            return None
        return max(live, key=lambda member: (member[0].version, member[0].revision or 0))

    newer_versions = [m for m in members if m[0].version > filename_info.version]
    locked_by = blocker(newer_versions)
    if locked_by is not None:
        return locked_by
    newer_revisions = [
        m
        for m in members
        if m[0].version == filename_info.version and (m[0].revision or 0) > (filename_info.revision or 0)
    ]
    return blocker(newer_revisions)
