"""Where observations come from (SPEC 10). v1 has one source: a user's observations."""

from typing import Protocol

from inat_anki.api import INatClient
from inat_anki.model import Observation, TaxonAncestry
from inat_anki.normalise import ancestry_from_api, observation_from_api


class Source(Protocol):
    source_key: str

    def fetch(self) -> list[Observation]: ...


class UserObservationsSource:
    """All research-grade observations of one user."""

    def __init__(self, client: INatClient, login: str, place_id: int, locale: str = "en"):
        self.client = client
        self.login = login
        self.place_id = place_id
        self.locale = locale
        self.source_key = f"user:{login}"

    def params(self) -> dict:
        return {
            "user_login": self.login,
            "quality_grade": "research",
            "locale": self.locale,
            "preferred_place_id": self.place_id,
        }

    def fetch(self) -> list[Observation]:
        return [observation_from_api(d) for d in self.client.iter_observations(self.params())]


def fetch_ancestries(
    client: INatClient,
    taxon_ids: set[int],
    known: dict[int, TaxonAncestry],
    locale: str,
    place_id: int,
) -> dict[int, TaxonAncestry]:
    """Ancestry for taxa not already known (one request per 30 taxa)."""
    missing = sorted(taxon_ids - set(known))
    if not missing:
        return {}
    found = {}
    for d in client.get_taxa(missing, locale, place_id):
        ancestry = ancestry_from_api(d)
        found[ancestry.taxon_id] = ancestry
    return found
