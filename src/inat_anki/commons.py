"""Wikimedia Commons, through the MediaWiki API (SPEC-v2 6.2). Thin I/O layer."""

from inat_anki import __version__
from inat_anki.api import ApiError, INatClient
from inat_anki.breeds import commons_file_from_api
from inat_anki.model import CommonsFile

API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 1024
TITLES_BATCH = 50
MAXLAG_RETRIES = 3
EXTMETADATA = (
    "License|LicenseShortName|LicenseUrl|Artist|Attribution|AttributionRequired|Restrictions"
)


def user_agent() -> str:
    # Wikimedia's policy asks for a descriptive agent with a way to reach the operator.
    return f"inat-anki/{__version__} (https://github.com/Tom271/inat-anki)"


class CommonsClient:
    """Uses an HTTP client that shares the iNat client's rate limiter and daily counter."""

    def __init__(self, http: INatClient):
        self.http = http

    def _query(self, params: dict) -> dict:
        full = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "maxlag": "5",
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": str(THUMB_WIDTH),
            "iiextmetadatafilter": EXTMETADATA,
            **params,
        }
        for _ in range(MAXLAG_RETRIES + 1):
            data = self.http.get_json_url(API, full)
            error = data.get("error")
            if not error:
                return data
            if error.get("code") != "maxlag":
                raise ApiError(f"Commons API error: {error.get('code')}: {error.get('info')}")
            # The database is lagging: Wikimedia asks clients to wait and retry.
            self.http.clock.sleep(5)
        raise ApiError("Commons API kept reporting maxlag")

    @staticmethod
    def _files(data: dict) -> list[CommonsFile]:
        pages = data.get("query", {}).get("pages", [])
        return [f for f in (commons_file_from_api(p) for p in pages) if f]

    def category_files(self, category: str, limit: int = 50) -> list[CommonsFile]:
        return self._files(
            self._query(
                {
                    "generator": "categorymembers",
                    "gcmtitle": f"Category:{category}",
                    "gcmtype": "file",
                    "gcmlimit": str(limit),
                }
            )
        )

    def search_files(self, query: str, limit: int = 30) -> list[CommonsFile]:
        return self._files(
            self._query(
                {
                    "generator": "search",
                    "gsrsearch": f'"{query}"',
                    "gsrnamespace": "6",
                    "gsrlimit": str(limit),
                }
            )
        )

    def file_info(self, titles: list[str]) -> dict[str, CommonsFile]:
        """Fresh metadata for these titles; missing (deleted) files are absent."""
        out: dict[str, CommonsFile] = {}
        for start in range(0, len(titles), TITLES_BATCH):
            batch = titles[start : start + TITLES_BATCH]
            data = self._query({"titles": "|".join(batch)})
            renamed = {n["to"]: n["from"] for n in data.get("query", {}).get("normalized", [])}
            for f in self._files(data):
                out[renamed.get(f.title, f.title)] = f
        return out
