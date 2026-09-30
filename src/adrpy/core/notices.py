"""Warnings a shared helper raises without a command's own warnings list
at hand -- reading a config is done by every command. `main` collects them
for one run and adds them to the answer's warnings."""

import contextlib
import contextvars

_collected = contextvars.ContextVar("notices", default=None)


@contextlib.contextmanager
def collecting():
    """The notices raised while the block runs, as a list."""
    token = _collected.set([])
    try:
        yield _collected.get()
    finally:
        _collected.reset(token)


def notice(message):
    """Records `message` for the answer, once; outside `collecting`
    (a direct call from a test or a helper script) it goes nowhere."""
    collected = _collected.get()
    if collected is not None and message not in collected:
        collected.append(message)
