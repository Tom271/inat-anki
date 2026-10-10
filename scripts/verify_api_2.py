"""Follow-up live checks (SPEC section 2). Usage: uv run python scripts/verify_api_2.py <login>"""

import json
import sys
from pathlib import Path

from verify_api import API, OUT, save, session, throttled


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    obs = json.loads((OUT / "user_observations.json").read_text())["results"]

    # Own obscured observations
    keys = (
        "obscured",
        "geoprivacy",
        "taxon_geoprivacy",
        "place_guess",
        "location",
        "positional_accuracy",
        "public_positional_accuracy",
    )
    for o in obs:
        if o["obscured"]:
            print("  own obscured", o["id"], {k: o.get(k) for k in keys})

    # Common names that should differ in the UK
    names = {}
    for taxon in ("Turdus merula", "Pica pica", "Columba palumbus", "Troglodytes troglodytes"):
        for label, extra in (("uk", {"preferred_place_id": 6857}), ("none", {})):
            r = throttled(
                "GET",
                f"{API}/observations",
                params={"taxon_name": taxon, "per_page": 1, "locale": "en", **extra},
            ).json()
            names[f"{taxon} [{label}]"] = r["results"][0]["taxon"].get("preferred_common_name")
    save("common_names_2", names)
    for k, v in names.items():
        print("  name", k, "->", v)

    # Batched taxa lookup of ancestors (order / family)
    ids = sorted({a for o in obs[:10] for a in o["taxon"]["ancestor_ids"]})[:30]
    r = throttled(
        "GET",
        f"{API}/taxa",
        params={
            "id": ",".join(map(str, ids)),
            "per_page": 30,
            "locale": "en",
            "preferred_place_id": 6857,
        },
    ).json()
    save("taxa_batch", r)
    print("  taxa requested", len(ids), "returned", len(r["results"]), "total", r["total_results"])
    for t in r["results"]:
        if t["rank"] in ("order", "family"):
            print("   ", t["id"], t["rank"], t["name"], t.get("preferred_common_name"))

    # S3 open-data host: a CC-licensed photo
    r = throttled(
        "GET",
        f"{API}/observations",
        params={"photo_license": "cc-by", "per_page": 20, "quality_grade": "research"},
    ).json()
    s3 = [p for o in r["results"] for p in o["photos"] if "amazonaws" in p["url"]]
    print("  s3 photos found", len(s3), "of", sum(len(o["photos"]) for o in r["results"]))
    sizes = {}
    if s3:
        p = s3[0]
        print("  cc photo", p["license_code"], "|", p["attribution"])
        for size in ("square", "medium", "large", "original"):
            u = p["url"].replace("square", size)
            h = throttled("HEAD", u, headers={"Origin": "https://example.org"})
            sizes[size] = {
                "url": u,
                "status": h.status_code,
                "content_length": h.headers.get("Content-Length"),
                "cors": h.headers.get("Access-Control-Allow-Origin"),
            }
            print(
                "  s3",
                size,
                h.status_code,
                h.headers.get("Content-Length"),
                "CORS:",
                h.headers.get("Access-Control-Allow-Origin"),
            )
    save("photo_sizes_s3", sizes)

    # Static host: a real GET with Origin, in case HEAD omits CORS headers
    url = obs[0]["photos"][0]["url"].replace("square", "medium")
    g = throttled("GET", url, headers={"Origin": "https://example.org"})
    print("  static GET CORS:", g.headers.get("Access-Control-Allow-Origin"), len(g.content))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
