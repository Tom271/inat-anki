from inat_anki.throttle import RateLimiter, Throttle


class FakeClock:
    """Time only moves when something sleeps."""

    def __init__(self, start: float = 1_760_000_000.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def fake_limiter(interval: float = 1.0, clock: FakeClock | None = None) -> RateLimiter:
    return RateLimiter(Throttle(interval, clock or FakeClock()))
