"""Structured, reported command failures (distinct from CLI usage errors)."""


class CommandError(Exception):
    def __init__(self, code, detail=None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
