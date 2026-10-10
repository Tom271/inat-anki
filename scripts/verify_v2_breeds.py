"""Live checks for farm-breed cards: iNat breed data and Wikimedia Commons photos.

Usage: uv run python scripts/verify_v2_breeds.py <login>
"""

import re
import sys
from pathlib import Path

from verify_api import API, save, session, throttled

COMMONS = "https://commons.wikimedia.org/w/api.php"
# Candidate Commons category names per breed; the first that exists is used.
BREEDS = {
    "cattle": {
        "Holstein Friesian": ["Holstein Friesian cattle", "Holstein cattle"],
        "Aberdeen Angus": ["Aberdeen Angus cattle", "Aberdeen-Angus cattle", "Angus cattle"],
        "Limousin": ["Limousin cattle"],
        "British Blue": ["British Blue cattle", "Belgian Blue cattle"],
        "Charolais": ["Charolais cattle"],
        "Simmental": ["Simmental cattle"],
        "Hereford": ["Hereford cattle"],
        "Beef Shorthorn": ["Beef Shorthorn cattle", "Shorthorn cattle"],
        "Jersey": ["Jersey cattle"],
        "Highland": ["Highland cattle"],
        "Welsh Black": ["Welsh Black cattle"],
    },
    "sheep": {
        "Texel": ["Texel sheep"],
        "Suffolk": ["Suffolk sheep"],
        "Welsh Mountain": ["Welsh Mountain sheep"],
        "Scottish Blackface": ["Scottish Blackface sheep", "Blackface sheep"],
        "Swaledale": ["Swaledale sheep"],
        "Lleyn": ["Lleyn sheep"],
        "North of England Mule": ["North of England Mule sheep", "Mule sheep", "Mule (sheep)"],
        "Bluefaced Leicester": ["Bluefaced Leicester sheep", "Blue-faced Leicester sheep"],
        "Cheviot": ["Cheviot sheep"],
        "Charollais": ["Charollais sheep"],
    },
    "pigs": {
        "Gloucestershire Old Spots": [
            "Gloucestershire Old Spots",
            "Gloucestershire Old Spots pigs",
        ],
        "British Saddleback": ["British Saddleback", "British Saddleback pigs"],
        "Oxford Sandy and Black": ["Oxford Sandy and Black", "Oxford Sandy and Black pigs"],
        "Tamworth": ["Tamworth pigs", "Tamworth pig", "Tamworth (pig)"],
        "Large Black": ["Large Black pigs", "Large Black pig", "Large Black (pig)"],
        "Berkshire": ["Berkshire pigs", "Berkshire pig", "Berkshire (pig)"],
    },
}
SHAREABLE = re.compile(r"^(cc0|pd|public domain|cc-by(-sa)?(-\d(\.\d)?)?)$", re.I)


def commons(params: dict) -> dict:
    return throttled(
        "GET", COMMONS, params={"format": "json", "formatversion": "2", **params}
    ).json()


def main(login: str) -> None:
    session.headers["User-Agent"] = (
        f"inat-anki/0.1.0 (https://github.com/Tom271/inat-anki; iNat user {login})"
    )

    # iNat: is there a breed observation field, and how much data is there?
    r = throttled("GET", f"{API}/observation_fields/autocomplete", params={"q": "breed"}).json()
    fields = [(f["id"], f["name"], f.get("values_count")) for f in r.get("results", [])][:8]
    print("  iNat breed fields:", fields)
    for taxon, tid in (("cattle", 74113), ("sheep", 121578), ("pig", 324492)):
        r = throttled(
            "GET",
            f"{API}/observations",
            params={
                "taxon_id": tid,
                "place_id": 6857,
                "per_page": 0,
                "photo_license": "cc0,cc-by,cc-by-sa",
            },
        ).json()
        print(
            f"  iNat UK {taxon} observations with shareable photos (any grade):", r["total_results"]
        )
    if fields:
        fid, fname, _ = fields[0]
        r = throttled(
            "GET",
            f"{API}/observations",
            params={"taxon_id": 74113, "place_id": 6857, "per_page": 0, f"field:{fname}": ""},
        ).json()
        print(f"  iNat UK cattle with field '{fname}' set:", r["total_results"])

    # Commons: resolve categories (one request for all candidate titles)
    titles = [
        f"Category:{c}" for group in BREEDS.values() for cands in group.values() for c in cands
    ]
    found = {}
    for i in range(0, len(titles), 50):
        r = commons(
            {"action": "query", "titles": "|".join(titles[i : i + 50]), "prop": "categoryinfo"}
        )
        for p in r["query"]["pages"]:
            if not p.get("missing") and p.get("categoryinfo"):
                found[p["title"]] = p["categoryinfo"]
    results = {}
    for group, breeds in BREEDS.items():
        for breed, cands in breeds.items():
            cat = next((f"Category:{c}" for c in cands if f"Category:{c}" in found), None)
            if not cat:
                print(f"  {group:6} {breed:26} NO CATEGORY")
                results[breed] = None
                continue
            r = commons(
                {
                    "action": "query",
                    "generator": "categorymembers",
                    "gcmtitle": cat,
                    "gcmtype": "file",
                    "gcmlimit": "50",
                    "prop": "imageinfo",
                    "iiprop": "url|mime|size|extmetadata",
                    "iiextmetadatafilter": "License|LicenseShortName|Artist|AttributionRequired",
                }
            )
            files = r.get("query", {}).get("pages", [])
            usable, licences = [], {}
            for f in files:
                ii = (f.get("imageinfo") or [{}])[0]
                md = ii.get("extmetadata", {})
                lic = md.get("License", {}).get("value", "")
                licences[lic] = licences.get(lic, 0) + 1
                if (
                    ii.get("mime") == "image/jpeg"
                    and max(ii.get("width", 0), ii.get("height", 0)) >= 1024
                    and SHAREABLE.match(lic)
                ):
                    usable.append(f["title"])
            results[breed] = {
                "category": cat,
                "files": found[cat].get("files"),
                "sampled": len(files),
                "usable_in_sample": len(usable),
                "licences": licences,
                "examples": usable[:3],
            }
            print(
                f"  {group:6} {breed:26} {cat} files={found[cat].get('files')} "
                f"sampled={len(files)} usable={len(usable)} licences={licences}"
            )
    save("v2_breeds_commons", results)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
