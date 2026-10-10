"""Find Commons categories for breeds the first pass missed; recheck iNat's Breed field.

Usage: uv run python scripts/verify_v2_breeds_2.py <login>
"""

import sys
from pathlib import Path

from verify_api import API, session, throttled
from verify_v2_breeds import commons

MISSING = [
    "Beef Shorthorn",
    "Welsh Black cattle",
    "Texel sheep",
    "Scottish Blackface",
    "Bluefaced Leicester",
    "Charollais sheep",
    "Lleyn sheep",
    "North of England Mule",
    "Beltex",
    "Herdwick",
]


def main(login: str) -> None:
    session.headers["User-Agent"] = (
        f"inat-anki/0.1.0 (https://github.com/Tom271/inat-anki; iNat user {login})"
    )
    for tid, name in ((74113, "cattle"), (121578, "sheep")):
        r = throttled(
            "GET",
            f"{API}/observations",
            params={"taxon_id": tid, "place_id": 6857, "per_page": 0, "field:Breed": ""},
        ).json()
        print(f"  iNat UK {name} with the Breed field set:", r["total_results"])
    for q in MISSING:
        r = commons(
            {
                "action": "query",
                "list": "search",
                "srsearch": q,
                "srnamespace": "14",
                "srlimit": "5",
            }
        )
        titles = [s["title"] for s in r["query"]["search"]]
        info = commons({"action": "query", "titles": "|".join(titles), "prop": "categoryinfo"})
        print(
            f"  {q:22}",
            [(p["title"], p.get("categoryinfo", {}).get("files")) for p in info["query"]["pages"]],
        )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
