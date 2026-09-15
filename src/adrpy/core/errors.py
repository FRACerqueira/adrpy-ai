"""Structured, reported command failures, and CLI usage errors -- kept as
two distinct exception types because they map to two different fixed exit
codes (harness Fase 0): an operation that was attempted and refused vs. a
malformed invocation of the command itself (unknown flag, missing value)."""


class CommandError(Exception):
    def __init__(self, code, detail=None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class UsageError(Exception):
    pass
