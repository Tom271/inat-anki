"""Commons-only options for thin breed categories: file sizes and uncategorised matches.

Usage: uv run python scripts/verify_v2_breeds_4.py <login>
"""

import sys
from pathlib import Path

from verify_api import session
from verify_v2_breeds import SHAREABLE, commons

THIN = {
    "Lleyn sheep": "Lleyn sheep",
    "Mule sheep": "mule sheep",
    "Beef Shorthorn": "Beef Shorthorn",
}


def describe(pages):
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        lic = (ii.get("extmetadata") or {}).get("License", {}).get("value", "")
        out.append(
            (
                p["title"][5:60],
                ii.get("mime"),
                max(ii.get("width", 0), ii.get("height", 0)),
                lic,
                bool(SHAREABLE.match(lic)),
            )
        )
    return out


def main(login: str) -> None:
    session.headers["User-Agent"] = (
        f"inat-anki/0.1.0 (https://github.com/Tom271/inat-anki; iNat user {login})"
    )
    for cat, query in THIN.items():
        r = commons(
            {
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": f"Category:{cat}",
                "gcmtype": "file",
                "gcmlimit": "50",
                "prop": "imageinfo",
                "iiprop": "mime|size|extmetadata",
                "iiextmetadatafilter": "License",
            }
        )
        print(f"  category {cat}:")
        for row in describe(r.get("query", {}).get("pages", [])):
            print("     ", row)
        r = commons(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": f'"{query}"',
                "gsrnamespace": "6",
                "gsrlimit": "30",
                "prop": "imageinfo",
                "iiprop": "mime|size|extmetadata",
                "iiextmetadatafilter": "License",
            }
        )
        rows = describe(r.get("query", {}).get("pages", []))
        ok = [x for x in rows if x[1] == "image/jpeg" and x[2] >= 1024 and x[4]]
        print(f'  search "{query}": {len(rows)} files, {len(ok)} shareable JPEG >= 1024 px')
        for row in ok[:6]:
            print("     ", row)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
