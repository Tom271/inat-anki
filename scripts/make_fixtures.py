"""Build anonymised test fixtures from responses saved by verify_api.py.

Usage: uv run python scripts/make_fixtures.py <login>
Makes one API request (taxa for the chosen observations), then writes tests/fixtures/.
"""

import copy
import json
import sys
from pathlib import Path

from verify_api import API, OUT, session, throttled

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
ANON_LOGIN = "example_user"
ANON_NAME = "Example User"

# Real observations chosen to cover the cases the tests need.
CHOSEN = [
    125757925,  # lower-case common name, Europe/London (BST)
    138594277,  # obscured, UK-specific common name
    166402825,  # four photos
    403884245,  # Europe/Paris, UK-specific common name
    405419599,  # subspecies
    405770862,  # bird, .jpg photo host path
    406515439,  # no common name
    406802316,  # Lucerne (UK) vs Alfalfa (global)
]

OBS_KEYS = [
    "id",
    "uuid",
    "uri",
    "quality_grade",
    "observed_on",
    "observed_on_string",
    "time_observed_at",
    "observed_time_zone",
    "time_zone_offset",
    "place_guess",
    "location",
    "positional_accuracy",
    "public_positional_accuracy",
    "obscured",
    "geoprivacy",
    "taxon_geoprivacy",
    "updated_at",
    "created_at",
    "user",
    "taxon",
    "photos",
    "observation_photos",
    "sounds",
]
TAXON_KEYS = [
    "id",
    "name",
    "rank",
    "rank_level",
    "preferred_common_name",
    "iconic_taxon_name",
    "ancestor_ids",
    "ancestry",
    "is_active",
]
PHOTO_KEYS = ["id", "url", "license_code", "attribution", "original_dimensions"]
ANCESTOR_KEYS = ["id", "name", "rank", "rank_level", "preferred_common_name"]


def pick(d: dict, keys: list[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


def anonymise(o: dict) -> dict:
    o = pick(o, OBS_KEYS)
    o["user"] = {"id": 1, "login": ANON_LOGIN, "name": ANON_NAME}
    o["taxon"] = pick(o["taxon"], TAXON_KEYS)
    o["photos"] = [pick(p, PHOTO_KEYS) for p in o["photos"]]
    for p in o["photos"]:
        p["attribution"] = p["attribution"].replace("Tom H", ANON_NAME)
    o["observation_photos"] = [
        {"id": op["id"], "position": op["position"], "photo_id": op["photo_id"]}
        for op in o["observation_photos"]
    ]
    if not o["obscured"]:
        # Coarsen precise locations of the real account before committing them.
        lat, lon = (float(x) for x in o["location"].split(","))
        o["location"] = f"{lat:.1f},{lon:.1f}"
        o["place_guess"] = "Example Park, Exampleton, England, GB"
    return o


def edge_cases(base: dict, genus: dict) -> list[dict]:
    """Synthetic observations for cases the real account does not have."""
    out = []

    sound_only = copy.deepcopy(base)
    sound_only.update(
        id=900000001,
        photos=[],
        observation_photos=[],
        sounds=[{"id": 1, "file_url": "https://example.org/sound.mp3"}],
    )
    out.append(sound_only)

    no_time = copy.deepcopy(base)
    no_time.update(id=900000002, time_observed_at=None, observed_on_string="2024-05-04")
    out.append(no_time)

    genus_level = copy.deepcopy(base)
    genus_level.update(id=900000003)
    genus_level["taxon"] = {
        "id": genus["id"],
        "name": genus["name"],
        "rank": "genus",
        "rank_level": genus["rank_level"],
        "preferred_common_name": genus.get("preferred_common_name"),
        "iconic_taxon_name": base["taxon"]["iconic_taxon_name"],
        "ancestor_ids": base["taxon"]["ancestor_ids"][:-1],
        "is_active": True,
    }
    out.append(genus_level)

    html_place = copy.deepcopy(base)
    html_place.update(id=900000004, place_guess='Fish & Chips <b>"Shop"</b> <script>x</script>')
    out.append(html_place)

    no_location = copy.deepcopy(base)
    no_location.update(
        id=900000005,
        location=None,
        positional_accuracy=None,
        public_positional_accuracy=None,
        place_guess=None,
    )
    out.append(no_location)
    return out


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    obs = {o["id"]: o for o in json.loads((OUT / "user_observations.json").read_text())["results"]}
    chosen = [anonymise(obs[i]) for i in CHOSEN]

    taxon_ids = sorted({o["taxon"]["id"] for o in chosen})
    taxa = throttled(
        "GET",
        f"{API}/taxa/{','.join(map(str, taxon_ids))}",
        params={"locale": "en", "preferred_place_id": 6857},
    ).json()["results"]
    taxa = [
        {**pick(t, TAXON_KEYS), "ancestors": [pick(a, ANCESTOR_KEYS) for a in t["ancestors"]]}
        for t in taxa
    ]

    base = chosen[0]
    base_taxon = next(t for t in taxa if t["id"] == base["taxon"]["id"])
    genus = next(a for a in base_taxon["ancestors"] if a["rank"] == "genus")
    edges = edge_cases(base, genus)
    taxa.append(
        {
            **{k: edges[2]["taxon"][k] for k in edges[2]["taxon"]},
            "ancestors": [a for a in base_taxon["ancestors"] if a["id"] != genus["id"]],
        }
    )

    FIXTURES.mkdir(parents=True, exist_ok=True)
    page = {"total_results": len(chosen), "page": 1, "per_page": 200, "results": chosen}
    (FIXTURES / "observations_page.json").write_text(json.dumps(page, indent=2) + "\n")
    edge_page = {"total_results": len(edges), "page": 1, "per_page": 200, "results": edges}
    (FIXTURES / "observations_edge_cases.json").write_text(json.dumps(edge_page, indent=2) + "\n")
    taxa_page = {"total_results": len(taxa), "page": 1, "per_page": 30, "results": taxa}
    (FIXTURES / "taxa.json").write_text(json.dumps(taxa_page, indent=2) + "\n")
    print(f"wrote {len(chosen)} observations, {len(edges)} edge cases, {len(taxa)} taxa")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
