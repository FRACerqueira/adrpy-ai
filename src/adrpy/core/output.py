"""JSON output contract shared by every command.

A failure's human-readable explanation (`detail`) is part of the stdout
JSON and is also written, as the same text, to stderr -- a copy for a
human watching a terminal while stdout is piped, outside the contract
(ADR0010V01). `detail`'s wording is for people: callers decide on `code`
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
    # `is not None`, not truthiness: an empty list means the command's
    # attach_warnings region started, so the key is present as on success;
    # None means it never did (a raw error caught in __main__), and the
    # key is omitted.
    if warnings is not None:
        payload["warnings"] = warnings
    print(json.dumps(payload))
    if detail:
        print(detail, file=sys.stderr)
    return EXIT_FAILURE


def emit_usage_failure(code, detail=None):
    """Same JSON envelope as emit_failure, for a malformed CLI invocation
    (unknown verb, unknown flag, missing required value), with exit code
    2 instead of 1 -- one failure shape on stdout, whichever layer caught
    the mistake."""
    payload = {"success": False, "code": code}
    if detail:
        payload["detail"] = detail
    print(json.dumps(payload))
    if detail:
        print(detail, file=sys.stderr)
    return EXIT_USAGE_ERROR
