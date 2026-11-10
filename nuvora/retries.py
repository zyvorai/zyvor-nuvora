# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Simple exponential-backoff retries for provider calls."""
import time
from .security import Fault

def with_retries(fn, max_retries=2, base_delay=0.5, max_delay=8.0):
    """Call fn(); on transient Fault retry up to max_retries with backoff.
    Transient = 502/503/504 or message containing 'timeout'/'temporarily'.
    """
    last = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Fault as exc:
            last = exc
            msg = str(exc).lower()
            transient = exc.status in (502, 503, 504) or any(w in msg for w in ('timeout', 'temporarily', 'rate', 'unavailable'))
            if not transient or attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            time.sleep(delay)
    raise last
