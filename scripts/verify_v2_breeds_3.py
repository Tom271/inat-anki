"""Check the Wikipedia articles and final Commons categories for the breed list.

Usage: uv run python scripts/verify_v2_breeds_3.py <login>
"""

import sys
from pathlib import Path

from verify_api import session, throttled
from verify_v2_breeds import commons

WIKI = [
    "Holstein Friesian cattle",
    "Aberdeen Angus",
    "Limousin cattle",
    "British Blue cattle",
    "Charolais cattle",
    "Simmental cattle",
    "Hereford cattle",
    "Beef Shorthorn",
    "Jersey cattle",
    "Highland cattle",
    "Welsh Mountain sheep",
    "Scottish Blackface",
    "Swaledale sheep",
    "Lleyn sheep",
    "Texel sheep",
    "North of England Mule",
    "Bluefaced Leicester",
    "Suffolk sheep",
    "Cheviot sheep",
    "Charollais sheep",
    "Gloucestershire Old Spots",
    "British Saddleback",
    "Oxford Sandy and Black",
    "Tamworth pig",
    "Berkshire pig",
    "Large Black pig",
    "Belgian Blue",
    "Mule (sheep)",
    "Mule sheep",
]
CATEGORIES = [
    "Scottish Blackface",
    "Bluefaced Leicester",
    "Charollais",
    "Lleyn sheep",
    "Mule sheep",
]


def main(login: str) -> None:
    session.headers["User-Agent"] = (
        f"inat-anki/0.1.0 (https://github.com/Tom271/inat-anki; iNat user {login})"
    )
    r = throttled(
        "GET",
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "titles": "|".join(WIKI),
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
        },
    ).json()
    redirects = {x["from"]: x["to"] for x in r["query"].get("redirects", [])}
    pages = {p["title"]: not p.get("missing") for p in r["query"]["pages"]}
    for t in WIKI:
        final = redirects.get(t, t)
        print(f"  wiki {t:28} -> {final:32} {'ok' if pages.get(final) else 'MISSING'}")
    for cat in CATEGORIES:
        r = commons(
            {
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": f"Category:{cat}",
                "gcmtype": "file|subcat",
                "gcmlimit": "50",
                "prop": "imageinfo",
                "iiprop": "mime|size|extmetadata",
                "iiextmetadatafilter": "License",
            }
        )
        pages = r.get("query", {}).get("pages", [])
        files = [p for p in pages if p.get("imageinfo")]
        subcats = [p["title"] for p in pages if p["title"].startswith("Category:")]
        lic = {}
        for f in files:
            v = (f["imageinfo"][0].get("extmetadata") or {}).get("License", {}).get("value", "")
            lic[v] = lic.get(v, 0) + 1
        print(f"  commons {cat:22} files={len(files)} subcats={subcats[:4]} licences={lic}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
