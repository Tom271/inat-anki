"""Common-name resolution check (SPEC 2.2). Usage: uv run python scripts/verify_api_3.py <login>"""

import json
import sys
from pathlib import Path

from verify_api import API, OUT, save, session, throttled


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    uk = json.loads((OUT / "user_observations.json").read_text())["results"]
    base = {
        "user_login": login,
        "quality_grade": "research",
        "per_page": 200,
        "order_by": "id",
        "order": "asc",
    }
    variants = {
        "none": throttled("GET", f"{API}/observations", params=base).json()["results"],
        "en": throttled("GET", f"{API}/observations", params={**base, "locale": "en"}).json()[
            "results"
        ],
        "en-GB": throttled(
            "GET",
            f"{API}/observations",
            params={**base, "locale": "en-GB", "preferred_place_id": 6857},
        ).json()["results"],
    }
    diffs = []
    for i, o in enumerate(uk):
        row = {"name": o["taxon"]["name"], "en+uk": o["taxon"].get("preferred_common_name")}
        for k, v in variants.items():
            row[k] = v[i]["taxon"].get("preferred_common_name")
        if len(set(row.values()) - {row["name"]}) > 1:
            diffs.append(row)
    save("common_names_variants", diffs)
    print("  observations whose name differs across variants:", len(diffs))
    for d in diffs:
        print("   ", d)

    r = throttled("GET", f"{API}/taxa/12716", params={"all_names": "true"}).json()["results"][0]
    en = [
        (n["name"], n.get("position"), [p.get("place_id") for p in n.get("place_taxon_names", [])])
        for n in r.get("names", [])
        if n.get("locale") == "en"
    ]
    save("blackbird_names", r.get("names", []))
    print("  Turdus merula en names (name, position, place_ids):", en)
    t = throttled(
        "GET",
        f"{API}/observations",
        params={"taxon_id": 12716, "per_page": 1, "locale": "en", "preferred_place_id": 6857},
    ).json()["results"][0]["taxon"]
    print("  taxon_id=12716 with UK ->", t["name"], t.get("preferred_common_name"))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
