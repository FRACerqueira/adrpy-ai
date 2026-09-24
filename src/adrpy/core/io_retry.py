"""Shared transient-I/O retry helper: the same Windows "pending
delete"/sharing-violation contention window this project already retries
on the write side
(atomic_write.py, its own exponential backoff empirically tuned for a
busier concurrent-writer case) also applies to reading any file
mid-scan -- extracted here instead of repeating the same read-retry loop.
"""

import time

IO_RETRY_ATTEMPTS = 3
IO_RETRY_DELAY_SECONDS = 0.05


def read_with_permission_retry(read, attempts=IO_RETRY_ATTEMPTS, delay=IO_RETRY_DELAY_SECONDS):
    """Calls the zero-arg `read` callable, retrying up to `attempts` times
    on a transient PermissionError (flat delay -- unlike atomic_write's
    own exponential backoff; this is the lighter read-side case). Any other
    exception, including FileNotFoundError, is never retried and
    propagates on the first occurrence. Re-raises the PermissionError
    itself once `attempts` is exhausted."""
    for attempt in range(attempts):
        try:
            return read()
        except PermissionError:
            if attempt >= attempts - 1:
                raise
            time.sleep(delay)
