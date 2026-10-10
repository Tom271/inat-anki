"""Why are some common trees missing from the multi-ID ranking?"""

import sys
from pathlib import Path

from verify_api import API, session, throttled


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    base = {"place_id": 6857, "quality_grade": "research", "rank": "species"}
    for tid in sys.argv[2:]:
        r = throttled(
            "GET",
            f"{API}/observations/species_counts",
            params={**base, "taxon_id": tid, "per_page": 3},
        ).json()
        print(
            "  single",
            tid,
            [(x["taxon"]["id"], x["taxon"]["name"], x["count"]) for x in r["results"]],
        )
    ids = [
        line.split("\t")[0]
        for line in (Path(__file__).parent.parent / "lists/uk-trees.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    for size in (40, 79):
        r = throttled(
            "GET",
            f"{API}/observations/species_counts",
            params={**base, "taxon_id": ",".join(ids[:size]), "per_page": 500},
        ).json()
        got = {x["taxon"]["id"] for x in r["results"]}
        print(
            f"  multi first {size}: results={len(r['results'])} total={r['total_results']}"
            f" listed found={len(got & set(map(int, ids[:size])))}"
        )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
