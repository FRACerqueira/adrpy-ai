"""Structured, reported command failures, and CLI usage errors -- kept as
two distinct exception types because they map to two different fixed exit
codes: an operation that was attempted and refused vs. a malformed
invocation of the command itself (unknown flag, missing value)."""


class CommandError(Exception):
    def __init__(self, code, detail=None, data=None, warnings=None):
        """`data`: a structured payload for a failure that isn't fully
        explained by `code` alone -- e.g. not-latest-version needs to
        name WHICH version actually is the latest, which a fixed code
        string can't carry and `detail` (stderr-only free text) isn't
        part of the JSON contract.

        `warnings`: a real side effect (an encoding repair, an
        orphan-temp-file cleanup, a stale-lock reclaim, a retried write)
        can already have happened before this
        same command run goes on to fail for an unrelated reason -- e.g.
        `reject` can finish rewriting the target file's own status
        before discovering its predecessor is missing. Without this, that
        warning was silently dropped the moment the run ended in failure
        instead of success, even though the side effect was real."""
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.data = data
        self.warnings = warnings


class UsageError(Exception):
    pass
