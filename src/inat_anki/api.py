"""HTTP access to the iNaturalist API and photo hosts. Thin I/O layer."""

from collections.abc import Iterator
from email.utils import parsedate_to_datetime

import requests

from inat_anki import __version__
from inat_anki.throttle import RateLimiter

API_BASE = "https://api.inaturalist.org/v1"
PER_PAGE = 200  # the API maximum
TAXA_BATCH = 30  # ids per GET /v1/taxa/{ids}
RETRY_DELAYS = (2, 4, 8, 16, 32)  # seconds, then fail
TIMEOUT = 30


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def user_agent(login: str) -> str:
    return f"inat-anki/{__version__} ({login})"


def retry_after_seconds(response: requests.Response, now: float) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        return max(parsedate_to_datetime(value).timestamp() - now, 0.0)
    except (TypeError, ValueError):
        return None


class INatClient:
    def __init__(
        self,
        limiter: RateLimiter,
        login: str,
        session: requests.Session | None = None,
        on_retry=None,
    ):
        self.limiter = limiter
        self.clock = limiter.clock
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent(login)
        self.on_retry = on_retry or (lambda delay, reason: None)

    def _request(self, url: str, params: dict | None = None, expected_bytes: int = 0):
        """GET through the rate limiter, retrying 429, 5xx and connection errors."""
        for attempt in range(len(RETRY_DELAYS) + 1):
            # Retries are requests too: they count against the daily limit and the throttle.
            self.limiter.before_request(expected_bytes)
            try:
                response = self.session.get(url, params=params, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout) as e:
                response, reason = None, f"{type(e).__name__}"
            else:
                if response.status_code != 429 and response.status_code < 500:
                    break
                reason = f"HTTP {response.status_code}"
            status = response.status_code if response is not None else None
            if attempt == len(RETRY_DELAYS):
                raise ApiError(f"{url}: {reason} after {attempt + 1} attempts", status)
            delay = RETRY_DELAYS[attempt]
            if response is not None:
                retry_after = retry_after_seconds(response, self.clock.time())
                if retry_after is not None:
                    delay = retry_after
            self.on_retry(delay, reason)
            self.clock.sleep(delay)
        if not response.ok:
            raise ApiError(f"{url}: HTTP {response.status_code}", response.status_code)
        return response

    def get_json(self, path: str, params: dict | None = None) -> dict:
        return self._request(f"{API_BASE}{path}", params).json()

    def iter_observations(self, params: dict) -> Iterator[dict]:
        """Every observation matching `params`, paging by id_above (works past 10k)."""
        id_above = 0
        while True:
            page = self.get_json(
                "/observations",
                {
                    **params,
                    "per_page": PER_PAGE,
                    "order_by": "id",
                    "order": "asc",
                    "id_above": id_above,
                },
            )
            results = page["results"]
            yield from results
            if len(results) < PER_PAGE:
                return
            id_above = results[-1]["id"]

    def get_taxa(self, ids: list[int], locale: str, place_id: int) -> list[dict]:
        """Taxa with their full `ancestors`, TAXA_BATCH ids per request."""
        out = []
        for start in range(0, len(ids), TAXA_BATCH):
            batch = ",".join(str(i) for i in ids[start : start + TAXA_BATCH])
            page = self.get_json(
                f"/taxa/{batch}", {"locale": locale, "preferred_place_id": place_id}
            )
            out.extend(page["results"])
        return out

    def download(self, url: str, expected_bytes: int) -> bytes:
        response = self._request(url, expected_bytes=expected_bytes)
        data = response.content
        self.limiter.record_bytes(len(data))
        return data
