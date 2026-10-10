"""API JSON -> model dataclasses. Pure: no I/O."""

from inat_anki.model import Observation, Photo, RankedTaxon, Taxon, TaxonAncestry

PHOTO_SIZES = ("large", "medium")


def photo_from_api(d: dict) -> Photo:
    return Photo(
        id=d["id"],
        url=d["url"],
        license_code=d.get("license_code"),
        attribution=d.get("attribution") or "",
    )


def taxon_from_api(d: dict) -> Taxon:
    return Taxon(
        id=d["id"],
        name=d["name"],
        rank=d["rank"],
        common_name=d.get("preferred_common_name") or None,
        iconic_taxon_name=d.get("iconic_taxon_name"),
        ancestor_ids=tuple(d.get("ancestor_ids") or ()),
    )


def _parse_location(location: str | None) -> tuple[float | None, float | None]:
    if not location:
        return None, None
    lat, lon = location.split(",")
    return float(lat), float(lon)


def observation_from_api(d: dict) -> Observation:
    lat, lon = _parse_location(d.get("location"))
    return Observation(
        id=d["id"],
        user_login=d["user"]["login"],
        taxon=taxon_from_api(d["taxon"]),
        photos=tuple(photo_from_api(p) for p in d.get("photos") or ()),
        observed_on=d.get("observed_on"),
        time_observed_at=d.get("time_observed_at"),
        place_guess=d.get("place_guess") or None,
        latitude=lat,
        longitude=lon,
        accuracy_m=d.get("public_positional_accuracy"),
        obscured=bool(d.get("obscured")),
        updated_at=d["updated_at"],
    )


def ancestry_from_api(d: dict) -> TaxonAncestry:
    """From one result of GET /v1/taxa/{ids}, which includes `ancestors`."""
    ranks = {a["rank"]: a["name"] for a in d.get("ancestors") or ()}
    ranks.setdefault(d["rank"], d["name"])
    return TaxonAncestry(taxon_id=d["id"], order=ranks.get("order"), family=ranks.get("family"))


def photo_url(photo: Photo, size: str) -> str:
    if size not in PHOTO_SIZES:
        raise ValueError(f"unknown photo size {size!r}")
    head, sep, tail = photo.url.rpartition("/square.")
    if not sep:
        raise ValueError(f"not a square photo URL: {photo.url}")
    return f"{head}/{size}.{tail}"


def photo_ext(photo: Photo) -> str:
    """File extension from the URL (iNat uses both jpg and jpeg)."""
    tail = photo.url.rsplit("/", 1)[-1].split("?", 1)[0]
    _, dot, ext = tail.rpartition(".")
    return ext.lower() if dot and ext else "jpg"


def media_filename(photo: Photo) -> str:
    return f"inat_{photo.id}.{photo_ext(photo)}"


def ranked_from_api(d: dict) -> RankedTaxon:
    """One result of GET /v1/observations/species_counts."""
    return RankedTaxon(taxon=taxon_from_api(d["taxon"]), count=d["count"])
