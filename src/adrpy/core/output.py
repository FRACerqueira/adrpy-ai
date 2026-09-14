"""JSON output contract shared by every command (harness Fase 0)."""

import json
import sys

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2


def emit_success(data):
    print(json.dumps({"success": True, "data": data}))
    return EXIT_SUCCESS


def emit_failure(code, detail=None):
    print(json.dumps({"success": False, "code": code}))
    if detail:
        print(detail, file=sys.stderr)
    return EXIT_FAILURE
