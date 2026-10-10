"""Rate limiting shared by API calls and photo downloads (SPEC 6).

iNat asks for about 1 request/s and about 10k requests/day. More than 5 GB of media per
hour can earn a permanent block, so the media limit has no tolerance added.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

MAX_RATE = 1.1  # requests/second: iNat's 1/s plus 10%
MIN_INTERVAL = 0.91  # seconds; never lower, whatever the rate
DEFAULT_INTERVAL = 1.0
DAILY_REQUEST_LIMIT = 11_000  # 10k plus 10%
HOURLY_BYTES_LIMIT = 4_500_000_000  # safety margin under 5 GB; no tolerance on media
BANDWIDTH_WINDOW_S = 3600.0


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def time(self) -> float: ...  # Unix seconds, for limits persisted across runs
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class RateTooHighError(ValueError):
    pass


class DailyLimitError(RuntimeError):
    pass


def interval_for_rate(rate: float) -> float:
    if rate <= 0:
        raise RateTooHighError(f"rate must be positive, got {rate}")
    if rate > MAX_RATE:
        raise RateTooHighError(f"rate {rate}/s is above the maximum of {MAX_RATE}/s")
    # 1/1.1 is 0.909..., which rounds below the 0.91 s floor; the floor wins.
    return max(1.0 / rate, MIN_INTERVAL)


class Throttle:
    """Spaces requests at least `min_interval` seconds apart, including within a burst."""

    def __init__(self, min_interval: float = DEFAULT_INTERVAL, clock: Clock | None = None):
        if min_interval < MIN_INTERVAL:
            raise RateTooHighError(f"interval {min_interval}s is below {MIN_INTERVAL}s")
        self.min_interval = min_interval
        self.clock = clock or SystemClock()
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self._last + self.min_interval - self.clock.monotonic()
            if remaining > 0:
                self.clock.sleep(remaining)
        self._last = self.clock.monotonic()


def utc_day(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, UTC).date().isoformat()


@dataclass
class DailyCounter:
    """Requests made per UTC day, persisted in state."""

    day: str = ""
    count: int = 0
    limit: int = DAILY_REQUEST_LIMIT
    force: bool = False

    def increment(self, now: float) -> None:
        today = utc_day(now)
        if today != self.day:
            self.day, self.count = today, 0
        if self.count >= self.limit and not self.force:
            raise DailyLimitError(
                f"{self.count} requests already made today (UTC); the limit is {self.limit}. "
                "Try again tomorrow, or pass --force."
            )
        self.count += 1

    def used_today(self, now: float) -> int:
        return self.count if self.day == utc_day(now) else 0


@dataclass
class BandwidthWindow:
    """Bytes downloaded in the rolling last hour, persisted in state."""

    entries: list[tuple[float, int]] = field(default_factory=list)
    limit: int = HOURLY_BYTES_LIMIT

    def _prune(self, now: float) -> None:
        self.entries = [(t, b) for t, b in self.entries if now - t < BANDWIDTH_WINDOW_S]

    def used(self, now: float) -> int:
        self._prune(now)
        return sum(b for _, b in self.entries)

    def wait_seconds(self, now: float, upcoming: int) -> float:
        """How long to pause so that `upcoming` more bytes stay within the hourly limit."""
        self._prune(now)
        excess = sum(b for _, b in self.entries) + upcoming - self.limit
        if excess <= 0:
            return 0.0
        for t, b in self.entries:  # oldest first: wait until enough of them age out
            excess -= b
            if excess <= 0:
                return t + BANDWIDTH_WINDOW_S - now
        return 0.0  # a single download bigger than the limit; waiting cannot help

    def record(self, now: float, nbytes: int) -> None:
        self.entries.append((now, nbytes))


class RateLimiter:
    """One gate for every request: throttle, daily counter and bandwidth window."""

    def __init__(
        self,
        throttle: Throttle,
        daily: DailyCounter | None = None,
        bandwidth: BandwidthWindow | None = None,
        on_pause=None,
    ):
        self.throttle = throttle
        self.clock = throttle.clock
        self.daily = daily or DailyCounter()
        self.bandwidth = bandwidth or BandwidthWindow()
        self.on_pause = on_pause or (lambda seconds, reason: None)

    def before_request(self, expected_bytes: int = 0) -> None:
        if expected_bytes:
            pause = self.bandwidth.wait_seconds(self.clock.time(), expected_bytes)
            if pause > 0:
                self.on_pause(pause, "hourly download limit")
                self.clock.sleep(pause)
        self.daily.increment(self.clock.time())
        self.throttle.wait()

    def record_bytes(self, nbytes: int) -> None:
        self.bandwidth.record(self.clock.time(), nbytes)
