"""Structured, reported command failures, and CLI usage errors -- kept as
two distinct exception types because they map to two different fixed exit
codes (harness Fase 0): an operation that was attempted and refused vs. a
malformed invocation of the command itself (unknown flag, missing value)."""


class CommandError(Exception):
    def __init__(self, code, detail=None, data=None):
        """`data` (usability audit): a structured payload for a failure
        that isn't fully explained by `code` alone -- e.g. not-latest-
        version needs to name WHICH version actually is the latest,
        which a fixed code string can't carry and `detail` (stderr-only
        free text) isn't part of the JSON contract."""
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.data = data


class UsageError(Exception):
    pass
