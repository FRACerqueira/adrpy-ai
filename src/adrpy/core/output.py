"""JSON output contract shared by every command (harness Fase 0)."""

import json
import sys

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2


def emit_success(data):
    print(json.dumps({"success": True, "data": data}))
    return EXIT_SUCCESS


def emit_failure(code, detail=None, data=None, warnings=None):
    payload = {"success": False, "code": code}
    if data:
        payload["data"] = data
    # Round 4 (observability audit Finding 4 / test-adequacy audit Finding
    # 4): `if warnings:` treated an explicitly empty list (a command's own
    # attach_warnings region genuinely started, nothing to report yet) the
    # same as None (never started at all) -- contradicting round 3's own
    # "warnings always present" guarantee on the success side. `is not
    # None` distinguishes the two; a raw OSError/internal-error caught in
    # __main__ before any command's own region began still omits the key.
    if warnings is not None:
        payload["warnings"] = warnings
    print(json.dumps(payload))
    if detail:
        print(detail, file=sys.stderr)
    return EXIT_FAILURE


def emit_usage_failure(code, detail=None):
    """Same JSON-envelope contract as emit_failure, but for a malformed CLI
    invocation itself (unknown verb, unknown flag, missing required value)
    -- exit code 2, not 1. Usability/resilience audit: a UsageError used to
    print free text to stderr with NOTHING on stdout, forcing an agent to
    parse two different shapes of failure depending on which layer caught
    the mistake."""
    print(json.dumps({"success": False, "code": code}))
    if detail:
        print(detail, file=sys.stderr)
    return EXIT_USAGE_ERROR
