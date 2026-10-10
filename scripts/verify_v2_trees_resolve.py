"""Re-resolve the tree list with duplicate-aware matching and rank it.

Usage: uv run python scripts/verify_v2_trees_resolve.py <login>
"""

import sys
from pathlib import Path

from verify_api import API, save, session, throttled
from verify_v2_sets import TREES, resolve


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    trees = [(common, sci, resolve(sci)) for common, sci in TREES]
    save("v2_trees", trees)
    for common, sci, v in trees:
        if v.get("how") != "exact" or v.get("rank") != "species":
            print("  TREE", common, sci, v)
    ids = [v["id"] for _, _, v in trees if v["id"]]
    for quality in ("research", "research,casual"):
        r = throttled(
            "GET",
            f"{API}/observations/species_counts",
            params={
                "place_id": 6857,
                "quality_grade": quality,
                "rank": "species,hybrid",
                "taxon_id": ",".join(map(str, ids)),
                "per_page": 500,
            },
        ).json()
        rows = [
            (x["taxon"]["id"], x["taxon"]["name"], x["count"])
            for x in r["results"]
            if x["taxon"]["id"] in set(ids)
        ]
        save(f"v2_trees_ranked_{quality.replace(',', '_')}", rows)
        print(
            f"  ranked ({quality}): {len(rows)} of {len(ids)}; top 5 {rows[:5]}; "
            f"#50 {rows[49] if len(rows) >= 50 else None}"
        )
        print(
            "    missing:", [v["name"] for _, _, v in trees if v["id"] not in {r[0] for r in rows}]
        )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
