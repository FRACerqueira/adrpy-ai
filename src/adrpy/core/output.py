"""JSON output contract shared by every command.

A failure's human-readable explanation (`detail`) is part of the stdout
JSON and is also written, as the same text, to stderr -- a copy for a
human watching a terminal while stdout is piped, outside the contract
(ADR010V01). `detail`'s wording is for people: callers decide on `code`
and `data`, never by parsing `detail`.
"""

import json
import sys

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2


def explain(error):
    """An exception's message for `detail`, or its type name when the
    message is empty (`ValueError("")`, `OSError()`), so a failure never
    reaches a caller with no explanation at all."""
    if isinstance(error, OSError) and error.errno is not None and not (error.strerror or "").strip():
        name = f"{type(error).__name__} (errno {error.errno})"
        if not error.filename:
            return name
        return f"{name}: {error.filename} -> {error.filename2}" if error.filename2 else f"{name}: {error.filename}"
    return str(error).strip() or type(error).__name__


def emit_success(data):
    print(json.dumps({"success": True, "data": data}))
    return EXIT_SUCCESS


def emit_failure(code, detail=None, data=None, warnings=None):
    payload = {"success": False, "code": code}
    if detail:
        payload["detail"] = detail
    if data:
        payload["data"] = data
    # `if warnings:` would treat an explicitly empty list (a command's own
    # attach_warnings region genuinely started, nothing to report yet) the
    # same as None (never started at all) -- contradicting the "warnings
    # always present" guarantee on the success side. `is not None`
    # distinguishes the two; a raw OSError/internal-error caught in
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
    -- exit code 2, not 1. A UsageError printing free text to stderr with
    NOTHING on stdout would force an agent to parse two different shapes
    of failure depending on which layer caught the mistake."""
    payload = {"success": False, "code": code}
    if detail:
        payload["detail"] = detail
    print(json.dumps(payload))
    if detail:
        print(detail, file=sys.stderr)
    return EXIT_USAGE_ERROR
