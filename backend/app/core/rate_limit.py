"""A brake on repeated sign-in attempts from one source.

The per-account lockout in the portal already stops someone guessing five passwords
at *one* shop. It does nothing about the other shape of the same attack: one common
password tried against a thousand login ids, which never trips any single account's
counter. Nor does it stop a script simply hammering the endpoint — every attempt
costs a bcrypt hash, so a few hundred a second is a denial of service against a box
that is also running the warehouse.

This is deliberately small and in-process. A shared counter in Redis would be the
textbook answer, and would be the right change the day this runs behind more than one
worker — until then it would be infrastructure carrying no weight. The limitation is
real and worth stating plainly: with N workers, the effective limit is N times what
is configured here.
"""

from collections import defaultdict, deque
from time import monotonic

from fastapi import Request

from app.core.exceptions import AppException

# Windows are per source, per bucket. Sign-in is the only thing guarded: it is the
# one unauthenticated endpoint that does real work, and the only one worth guessing at.
_WINDOW_SECONDS = 60.0
_MAX_ATTEMPTS = 20

_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def client_key(request: Request) -> str:
    """Who is asking, as well as we can tell.

    Behind a reverse proxy the socket address is the proxy's, so the forwarded header
    is used when present. That header is caller-supplied and trivially spoofed when
    the app is exposed directly — which is exactly why the per-account lockout stays
    in place underneath. This narrows the blast radius; it is not the only wall.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(request: Request, bucket: str) -> None:
    """Count this attempt and refuse once the window is full.

    A sliding window rather than a fixed one: a fixed window lets an attacker fire a
    full allowance in the last second of one window and another in the first second
    of the next, which is twice the intended rate at the moment it matters most.
    """
    key = (bucket, client_key(request))
    now = monotonic()
    hits = _attempts[key]

    cutoff = now - _WINDOW_SECONDS
    while hits and hits[0] < cutoff:
        hits.popleft()

    if len(hits) >= _MAX_ATTEMPTS:
        raise AppException(
            429, "محاولات كثيرة خلال وقت قصير، يرجى الانتظار قليلاً ثم إعادة المحاولة."
        )

    hits.append(now)
    # Buckets for callers who have gone quiet would otherwise accumulate forever.
    # Cheap to do here rather than on a timer, and only when the map is large enough
    # for it to matter.
    if len(_attempts) > 2048:
        for stale_key in [k for k, v in _attempts.items() if not v or v[-1] < cutoff]:
            del _attempts[stale_key]


def reset() -> None:
    """Clear all counters — for tests, which must not inherit each other's attempts."""
    _attempts.clear()
