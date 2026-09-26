"""Regenerates doc/decision-log/INDEX.md from the entry files themselves.

Per the decision-log skill: the index is always generated, never hand-
maintained prose. Run this after adding, never after editing, an entry
(entries are never edited in place -- a correction is a new `retraction`
entry instead).

`adrpy log` (ADR003V01) regenerates the index itself as part of writing
an entry; this script exists for the manual/legacy path -- an entry
written by hand, or a repo predating that command.

Usage: python scripts/generate_decision_log_index.py
(requires adrpy installed, e.g. `pip install -e ".[dev]"` -- see CONTRIBUTING.md)
"""

from pathlib import Path

from adrpy.core.decision_log import regenerate_index

DECISION_LOG_DIR = Path(__file__).resolve().parent.parent / "doc" / "decision-log"

if __name__ == "__main__":
    count = regenerate_index(DECISION_LOG_DIR)
    print(f"Regenerated {DECISION_LOG_DIR / 'INDEX.md'} with {count} entries.")
