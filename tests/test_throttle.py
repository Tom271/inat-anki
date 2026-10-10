import pytest
import requests
import responses

from inat_anki.api import API_BASE, ApiError, INatClient, retry_after_seconds
from inat_anki.throttle import (
    BandwidthWindow,
    DailyCounter,
    DailyLimitError,
    RateLimiter,
    RateTooHighError,
    Throttle,
    interval_for_rate,
)
from tests.fakes import FakeClock, fake_limiter

OBS_URL = f"{API_BASE}/observations"


def test_never_faster_than_configured_rate():
    clock = FakeClock()
    throttle = Throttle(1.0, clock)
    starts = []
    for _ in range(5):
        throttle.wait()
        starts.append(clock.monotonic())
        clock.advance(0.2)  # the request itself took 0.2 s
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert all(g >= 1.0 - 1e-9 for g in gaps)
    assert clock.sleeps == pytest.approx([0.8] * 4)


def test_no_sleep_when_requests_are_already_slow():
    clock = FakeClock()
    throttle = Throttle(1.0, clock)
    throttle.wait()
    clock.advance(5)
    throttle.wait()
    assert clock.sleeps == []


@pytest.mark.parametrize("rate", [1.11, 2, 10])
def test_refuses_rate_above_ceiling(rate):
    with pytest.raises(RateTooHighError):
        interval_for_rate(rate)


@pytest.mark.parametrize("rate", [0, -1])
def test_refuses_non_positive_rate(rate):
    with pytest.raises(RateTooHighError):
        interval_for_rate(rate)


def test_ceiling_rate_uses_floor_interval():
    assert interval_for_rate(1.1) == 0.91
    assert interval_for_rate(1.0) == 1.0
    assert interval_for_rate(0.5) == 2.0


def test_throttle_refuses_interval_below_floor():
    with pytest.raises(RateTooHighError):
        Throttle(0.9)


def test_daily_counter_refuses_over_limit_and_resets_next_day():
    clock = FakeClock(start=1_760_054_400.0)  # 2025-10-10 00:00 UTC
    counter = DailyCounter(limit=3)
    for _ in range(3):
        counter.increment(clock.time())
    with pytest.raises(DailyLimitError):
        counter.increment(clock.time())
    clock.advance(86_400)
    counter.increment(clock.time())
    assert counter.count == 1
    assert counter.used_today(clock.time()) == 1


def test_daily_counter_force_overrides():
    counter = DailyCounter(day="2025-10-10", count=11_000, force=True)
    counter.increment(1_760_054_400.0)
    assert counter.count == 11_001


def test_bandwidth_window_pauses_until_old_downloads_age_out():
    window = BandwidthWindow(limit=1000)
    window.record(0.0, 600)
    window.record(100.0, 300)
    assert window.wait_seconds(200.0, 100) == 0.0
    assert window.wait_seconds(200.0, 200) == pytest.approx(3400.0)  # first entry ages out
    assert window.wait_seconds(200.0, 800) == pytest.approx(3500.0)  # both must age out
    assert window.used(3700.0) == 0


def test_limiter_pauses_for_bandwidth():
    clock = FakeClock()
    limiter = RateLimiter(Throttle(1.0, clock), bandwidth=BandwidthWindow(limit=1000))
    limiter.record_bytes(900)
    limiter.before_request(expected_bytes=200)
    assert clock.sleeps == [pytest.approx(3600.0)]


@responses.activate
def test_backoff_on_429_honours_retry_after():
    responses.get(OBS_URL, status=429, headers={"Retry-After": "7"})
    responses.get(OBS_URL, status=429)
    responses.get(OBS_URL, json={"results": []})
    clock = FakeClock()
    client = INatClient(fake_limiter(clock=clock), "example_user")
    assert client.get_json("/observations") == {"results": []}
    # Throttle sleeps are under 1 s; the backoff sleeps are Retry-After, then the schedule.
    assert [s for s in clock.sleeps if s >= 1.0] == [7.0, 4.0]


@responses.activate
def test_backoff_schedule_then_fail():
    responses.get(OBS_URL, status=503)
    clock = FakeClock()
    limiter = fake_limiter(clock=clock)
    client = INatClient(limiter, "example_user")
    with pytest.raises(ApiError) as err:
        client.get_json("/observations")
    assert err.value.status == 503
    assert [s for s in clock.sleeps if s >= 2.0] == [2, 4, 8, 16, 32]
    assert len(responses.calls) == 6
    assert limiter.daily.count == 6  # retries count against the daily limit


@responses.activate
def test_connection_errors_are_retried():
    responses.get(OBS_URL, body=requests.ConnectionError("reset"))
    responses.get(OBS_URL, json={"results": []})
    client = INatClient(fake_limiter(), "example_user")
    assert client.get_json("/observations") == {"results": []}


@responses.activate
def test_client_errors_are_not_retried():
    responses.get(OBS_URL, status=404)
    client = INatClient(fake_limiter(), "example_user")
    with pytest.raises(ApiError) as err:
        client.get_json("/observations")
    assert err.value.status == 404
    assert len(responses.calls) == 1


def test_retry_after_http_date():
    response = requests.Response()
    response.headers["Retry-After"] = "Fri, 10 Oct 2025 00:00:30 GMT"
    assert retry_after_seconds(response, 1_760_054_400.0) == 30.0
    response.headers["Retry-After"] = "nonsense"
    assert retry_after_seconds(response, 0) is None
