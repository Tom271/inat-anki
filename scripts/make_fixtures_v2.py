"""Build anonymised v2 test fixtures from saved responses, plus one Commons request.

Usage: uv run python scripts/make_fixtures_v2.py <login>
Needs scripts/out/ from verify_v2.py. Writes tests/fixtures/v2_*.json.
"""

import copy
import json
import sys
from pathlib import Path

from verify_api import OUT, session, throttled
from verify_v2_breeds import COMMONS

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"

TAXON_KEYS = [
    "id",
    "name",
    "rank",
    "rank_level",
    "preferred_common_name",
    "iconic_taxon_name",
    "ancestor_ids",
    "is_active",
]
PHOTO_KEYS = ["id", "url", "license_code", "attribution", "original_dimensions"]
OBS_KEYS = [
    "id",
    "uri",
    "quality_grade",
    "observed_on",
    "time_observed_at",
    "place_guess",
    "obscured",
    "updated_at",
    "user",
    "taxon",
    "photos",
]


def pick(d: dict, keys: list[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


def species_counts() -> dict:
    raw = json.loads((OUT / "v2_species_counts_birds.json").read_text())
    results = [{"count": r["count"], "taxon": pick(r["taxon"], TAXON_KEYS)} for r in raw["results"]]
    return {
        "total_results": raw["total_results"],
        "page": 1,
        "per_page": len(results),
        "results": results,
    }


def licence_filtered_observations() -> dict:
    raw = json.loads((OUT / "v2_robin_cc_obs.json").read_text())
    names: dict[str, str] = {}
    results = []
    for o in raw["results"]:
        login = o["user"]["login"]
        anon = names.setdefault(login, f"observer_{len(names) + 1}")
        o = pick(o, OBS_KEYS)
        o["user"] = {"id": len(names), "login": anon, "name": anon.replace("_", " ").title()}
        o["taxon"] = pick(o["taxon"], TAXON_KEYS)
        photos = []
        for p in o["photos"]:
            p = pick(p, PHOTO_KEYS)
            label = p["attribution"].split(",", 1)[1] if "," in p["attribution"] else ""
            p["attribution"] = f"(c) {o['user']['name']},{label}"
            photos.append(p)
        o["photos"] = photos
        o["place_guess"] = "Example Place, UK"
        results.append(o)
    # Synthetic: one observation mixing a usable and an NC photo, and one ARR-only.
    mixed = copy.deepcopy(results[1])
    mixed["id"] = 900000101
    mixed["photos"][0]["id"] = 900000105
    mixed["photos"][1]["id"] = 900000102
    mixed["photos"][1]["license_code"] = "cc-by-nc"
    mixed["photos"][1]["attribution"] = (
        f"(c) {mixed['user']['name']}, some rights reserved (CC BY-NC)"
    )
    arr = copy.deepcopy(results[2])
    arr["id"] = 900000103
    arr["photos"][0]["id"] = 900000104
    arr["photos"][0]["license_code"] = None
    arr["photos"][0]["attribution"] = f"(c) {arr['user']['name']}, all rights reserved"
    results += [mixed, arr]
    return {"total_results": len(results), "page": 1, "per_page": 30, "results": results}


def commons_category(login: str) -> dict:
    session.headers["User-Agent"] = (
        f"inat-anki/0.1.0 (https://github.com/Tom271/inat-anki; iNat user {login})"
    )
    r = throttled(
        "GET",
        COMMONS,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "categorymembers",
            "gcmtitle": "Category:Hereford cattle",
            "gcmtype": "file",
            "gcmlimit": "12",
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": "1024",
            "iiextmetadatafilter": (
                "License|LicenseShortName|LicenseUrl|Artist|Attribution"
                "|AttributionRequired|Restrictions"
            ),
        },
    ).json()
    pages = r["query"]["pages"]
    for i, p in enumerate(pages):
        md = (p.get("imageinfo") or [{}])[0].get("extmetadata") or {}
        if isinstance(md, dict) and "Artist" in md:
            md["Artist"]["value"] = f'<a href="https://example.org/u{i}">Photographer {i}</a>'
        if isinstance(md, dict) and "Attribution" in md:
            md["Attribution"]["value"] = f"Photographer {i}"
    return {"query": {"pages": pages}}


def main(login: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = {
        "v2_species_counts.json": species_counts(),
        "v2_observations_cc.json": licence_filtered_observations(),
        "v2_commons_category.json": commons_category(login),
    }
    for name, data in out.items():
        (FIXTURES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print("wrote", name)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
