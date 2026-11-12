"""Injectable time source, so the sampler is deterministic under test."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Wall-clock time and a monotonic counter."""

    def now(self) -> datetime:
        """Return the current time as an aware UTC datetime."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic counter in seconds."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """Return ``time.monotonic()``."""
        return time.monotonic()


class FakeClock:
    """A clock that only moves when :meth:`advance` is called."""

    def __init__(self, start: datetime | None = None) -> None:
        self._start = start or datetime(2026, 9, 25, 20, 15, 0, tzinfo=UTC)
        self._elapsed = 0.0

    def now(self) -> datetime:
        """Return the start time plus the elapsed fake time."""
        return self._start + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        """Return the elapsed fake time."""
        return self._elapsed

    def advance(self, seconds: float) -> None:
        """Move time forward."""
        self._elapsed += max(seconds, 0.0)
