"""One-off checks of the live iNaturalist API (SPEC section 2).

Not part of the package. Saves raw responses to scripts/out/ (git-ignored).
Usage: uv run python scripts/verify_api.py <login>
"""

import json
import sys
import time
from pathlib import Path

import requests

API = "https://api.inaturalist.org/v1"
OUT = Path(__file__).parent / "out"
MIN_INTERVAL = 1.1

session = requests.Session()
_last = 0.0


def throttled(method: str, url: str, **kw) -> requests.Response:
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    r = session.request(method, url, timeout=30, **kw)
    print(f"{method} {r.status_code} {r.url}")
    return r


def save(name: str, data) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2))


def main(login: str) -> None:
    OUT.mkdir(exist_ok=True)
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"

    # 1. UK place id
    places = throttled("GET", f"{API}/places/autocomplete", params={"q": "United Kingdom"}).json()
    save("places_autocomplete", places)
    for p in places["results"][:5]:
        print("  place", p["id"], p["display_name"], p.get("admin_level"), p.get("place_type"))
    uk = next(p["id"] for p in places["results"] if p["name"] == "United Kingdom")

    # 2. The user's research-grade observations (also exercises paging params)
    obs = throttled(
        "GET",
        f"{API}/observations",
        params={
            "user_login": login,
            "quality_grade": "research",
            "per_page": 200,
            "order_by": "id",
            "order": "asc",
            "id_above": 0,
            "locale": "en",
            "preferred_place_id": uk,
        },
    ).json()
    save("user_observations", obs)
    print("  total_results", obs["total_results"], "returned", len(obs["results"]))

    # 2b. Common names for robin and herring gull, with and without UK preference
    names = {}
    for taxon in ("Erithacus rubecula", "Larus argentatus"):
        for label, extra in (("uk", {"preferred_place_id": uk}), ("none", {})):
            r = throttled(
                "GET",
                f"{API}/observations",
                params={"taxon_name": taxon, "per_page": 1, "locale": "en", **extra},
            ).json()
            t = r["results"][0]["taxon"]
            names[f"{taxon} [{label}]"] = t.get("preferred_common_name")
    save("common_names", names)
    for k, v in names.items():
        print("  name", k, "->", v)

    # 3. Photo sizes on both hosts (HEAD only; also record CORS headers)
    photo_urls = [p["url"] for o in obs["results"] for p in o["photos"]]
    hosts: dict[str, str] = {}
    for u in photo_urls:
        hosts.setdefault(u.split("/")[2], u)
    if "static.inaturalist.org" not in hosts:
        r = throttled(
            "GET", f"{API}/observations", params={"per_page": 50, "order_by": "id", "order": "asc"}
        ).json()
        for o in r["results"]:
            for p in o["photos"]:
                hosts.setdefault(p["url"].split("/")[2], p["url"])
    sizes = {}
    for host, url in hosts.items():
        for size in ("square", "medium", "large"):
            u = url.replace("square", size)
            h = throttled("HEAD", u, headers={"Origin": "https://example.org"})
            sizes[f"{host} {size}"] = {
                "url": u,
                "status": h.status_code,
                "content_length": h.headers.get("Content-Length"),
                "content_type": h.headers.get("Content-Type"),
                "access_control_allow_origin": h.headers.get("Access-Control-Allow-Origin"),
            }
    save("photo_sizes", sizes)
    for k, v in sizes.items():
        print(
            "  size", k, v["status"], v["content_length"], "CORS:", v["access_control_allow_origin"]
        )

    # 4. All-rights-reserved photos: find one among the user's photos, else globally
    arr = [p for o in obs["results"] for p in o["photos"] if p.get("license_code") is None]
    if not arr:
        r = throttled(
            "GET",
            f"{API}/observations",
            params={"photo_license": "none", "per_page": 5, "quality_grade": "research"},
        ).json()
        arr = [p for o in r["results"] for p in o["photos"] if p.get("license_code") is None]
    save("arr_photos", arr[:3])
    for p in arr[:3]:
        print("  ARR photo", p["id"], repr(p.get("license_code")), "|", p.get("attribution"))

    # 6. Obscured observations
    r = throttled(
        "GET",
        f"{API}/observations",
        params={"geoprivacy": "obscured", "per_page": 3, "quality_grade": "research"},
    ).json()
    save("obscured_observations", r)
    r2 = throttled(
        "GET",
        f"{API}/observations",
        params={"taxon_geoprivacy": "obscured", "per_page": 3, "quality_grade": "research"},
    ).json()
    save("taxon_obscured_observations", r2)
    keys = (
        "obscured",
        "geoprivacy",
        "taxon_geoprivacy",
        "place_guess",
        "location",
        "positional_accuracy",
        "public_positional_accuracy",
    )
    for o in r["results"] + r2["results"]:
        print("  obscured", o["id"], {k: o.get(k) for k in keys})


if __name__ == "__main__":
    main(sys.argv[1])
