"""Live checks for the v2 spec (common-species decks).

Usage: uv run python scripts/verify_v2.py <login>
"""

import sys
from pathlib import Path

from verify_api import API, save, session, throttled

GROUPS = [
    "Aves",
    "Fungi",
    "Lecanoromycetes",
    "Bryophyta",
    "Marchantiophyta",
    "Plantae",
    "Polypodiopsida",
    "Reptilia",
    "Amphibia",
    "Mammalia",
    "Pinopsida",
    "Magnoliopsida",
]


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    ids = {}
    for name in GROUPS:
        r = throttled(
            "GET", f"{API}/taxa", params={"q": name, "is_active": "true", "per_page": 5}
        ).json()
        t = next((t for t in r["results"] if t["name"] == name), None)
        ids[name] = t and {
            "id": t["id"],
            "rank": t["rank"],
            "common": t.get("preferred_common_name"),
        }
        print("  taxon", name, ids[name])
    save("v2_taxa", ids)

    base = {
        "place_id": 6857,
        "quality_grade": "research",
        "captive": "false",
        "rank": "species",
        "locale": "en",
        "preferred_place_id": 6857,
    }
    r = throttled(
        "GET",
        f"{API}/observations/species_counts",
        params={**base, "taxon_id": ids["Aves"]["id"], "per_page": 10},
    ).json()
    save("v2_species_counts_birds", r)
    print("  total bird species", r["total_results"])
    for x in r["results"]:
        t, p = x["taxon"], x["taxon"].get("default_photo") or {}
        print(
            f"    {x['count']:>7} {t['name']} | {t.get('preferred_common_name')} | "
            f"default photo licence {p.get('license_code')!r}"
        )

    # without_taxon_id: fungi excluding Lecanoromycetes
    r = throttled(
        "GET",
        f"{API}/observations/species_counts",
        params={
            **base,
            "taxon_id": ids["Fungi"]["id"],
            "without_taxon_id": ids["Lecanoromycetes"]["id"],
            "per_page": 5,
        },
    ).json()
    print("  fungi without lecanoromycetes:", [x["taxon"]["name"] for x in r["results"]])
    r = throttled(
        "GET",
        f"{API}/observations/species_counts",
        params={**base, "taxon_id": ids["Lecanoromycetes"]["id"], "per_page": 8},
    ).json()
    print(
        "  lecanoromycetes:",
        [(x["taxon"]["name"], x["taxon"].get("preferred_common_name")) for x in r["results"]],
    )

    # Licence-filtered observations for one species (robin)
    robin = 12748
    r = throttled(
        "GET",
        f"{API}/observations",
        params={
            "taxon_id": robin,
            "place_id": 6857,
            "quality_grade": "research",
            "photo_license": "cc0,cc-by,cc-by-sa",
            "order_by": "votes",
            "per_page": 5,
        },
    ).json()
    save("v2_robin_cc_obs", r)
    print("  robin cc obs total", r["total_results"])
    for o in r["results"]:
        print(
            "    obs",
            o["id"],
            o.get("cached_votes_total"),
            o.get("faves_count"),
            [(p["license_code"], p["url"].split("/")[2]) for p in o["photos"]],
        )

    # Multiple taxon_ids at once (for curated lists)
    r = throttled(
        "GET",
        f"{API}/observations/species_counts",
        params={**base, "taxon_id": "48256,54779,52855", "per_page": 5},
    ).json()
    print(
        "  multi taxon_id:",
        [(x["taxon"]["id"], x["taxon"]["name"], x["count"]) for x in r["results"]],
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
