"""Application-side monotonic UUIDv7 generator (RFC 9562 layout)."""
from __future__ import annotations
import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = -1
_last_random = 0
_RANDOM_MASK = (1 << 74) - 1

def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7, monotonic within one process and millisecond."""
    global _last_ms, _last_random
    with _lock:
        timestamp_ms = time.time_ns() // 1_000_000
        if timestamp_ms > _last_ms:
            _last_ms = timestamp_ms
            _last_random = secrets.randbits(74)
        else:
            # Clock rollback is handled by retaining the last timestamp and incrementing entropy.
            timestamp_ms = _last_ms
            _last_random = (_last_random + 1) & _RANDOM_MASK
            if _last_random == 0:
                while timestamp_ms <= _last_ms:
                    timestamp_ms = time.time_ns() // 1_000_000
                _last_ms = timestamp_ms
                _last_random = secrets.randbits(74)
        rand_a = (_last_random >> 62) & 0xFFF
        rand_b = _last_random & ((1 << 62) - 1)
        value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
        return uuid.UUID(int=value)
