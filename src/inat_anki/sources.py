"""Where observations come from (SPEC 10). v1 has one source: a user's observations."""

from typing import Protocol

from inat_anki.api import MAX_SPECIES, INatClient
from inat_anki.model import Observation, RankedTaxon, SetSpec, TaxonAncestry
from inat_anki.normalise import ancestry_from_api, observation_from_api, ranked_from_api


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


PHOTO_SEARCH_LICENCES = "cc0,cc-by,cc-by-sa"  # pre-filter; every photo is still checked
RANK_BUFFER = 25  # extra candidates, for species skipped for lack of photos


class PlaceSpeciesSource:
    """Common species of one place, for the species decks (SPEC-v2 4, 6.1)."""

    def __init__(self, client: INatClient, place_id: int, locale: str = "en"):
        self.client = client
        self.place_id = place_id
        self.locale = locale

    def _names(self) -> dict:
        return {"locale": self.locale, "preferred_place_id": self.place_id}

    def ranked(self, spec: SetSpec, taxon_ids: list[int], count: int) -> list[RankedTaxon]:
        params = {
            "place_id": self.place_id,
            "quality_grade": spec.quality_grade,
            "rank": spec.rank,
            "taxon_id": ",".join(str(i) for i in taxon_ids),
            **self._names(),
        }
        if spec.without_taxon_ids:
            params["without_taxon_id"] = ",".join(str(i) for i in spec.without_taxon_ids)
        # A species list asks for every listed ID: fetch the largest page to rank them all.
        per_page = MAX_SPECIES if spec.species_list else count + RANK_BUFFER
        return [ranked_from_api(d) for d in self.client.species_counts(params, per_page)]

    def photo_candidates(self, taxon_id: int, fallback: str | None = None) -> list[Observation]:
        """Observations with shareable-licensed photos (SPEC-v2 6.1).

        `fallback` is None (UK research grade), "cultivated" (UK casual cultivated with
        community agreement, for trees) or "world" (research grade anywhere).
        """
        params = {
            "taxon_id": taxon_id,
            "photo_license": PHOTO_SEARCH_LICENCES,
            "order_by": "votes",
            **self._names(),
        }
        if fallback == "cultivated":
            params.update(
                place_id=self.place_id,
                quality_grade="casual",
                captive="true",
                identifications="most_agree",
            )
        elif fallback == "world":
            params.update(quality_grade="research")
        else:
            params.update(place_id=self.place_id, quality_grade="research")
        return [observation_from_api(d) for d in self.client.search_observations(params)]

    def observations(self, ids: list[int]) -> dict[str, Observation]:
        return {str(d["id"]): observation_from_api(d) for d in self.client.observations_by_id(ids)}

    def taxa(self, ids: list[int]) -> list[dict]:
        return self.client.get_taxa(ids, self.locale, self.place_id)
