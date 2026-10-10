"""Live checks for the v2 set definitions: tree names, group IDs, previews.

Usage: uv run python scripts/verify_v2_sets.py <login>
"""

import json
import sys
from pathlib import Path

from verify_api import API, OUT, save, session, throttled

# Woodland Trust "A-Z of British trees" (79 entries) mapped to species. Copper beech and
# Irish yew are cultivars of Fagus sylvatica and Taxus baccata, so they are not separate
# species. "Cedar" -> cedar of Lebanon; "Eucalyptus" -> cider gum (the commonest planted
# in the UK); "Huntingdon elm" -> Dutch elm hybrid. The last two are common planted
# non-natives not in the Woodland Trust list.
TREES = [
    ("Alder", "Alnus glutinosa"),
    ("Alder buckthorn", "Frangula alnus"),
    ("Apple", "Malus domestica"),
    ("Ash", "Fraxinus excelsior"),
    ("Aspen", "Populus tremula"),
    ("Beech, common", "Fagus sylvatica"),
    ("Birch, downy", "Betula pubescens"),
    ("Birch, silver", "Betula pendula"),
    ("Blackthorn", "Prunus spinosa"),
    ("Box, common", "Buxus sempervirens"),
    ("Buckthorn, purging", "Rhamnus cathartica"),
    ("Cedar", "Cedrus libani"),
    ("Cherry, bird", "Prunus padus"),
    ("Cherry, sour", "Prunus cerasus"),
    ("Cherry, wild", "Prunus avium"),
    ("Chestnut, sweet", "Castanea sativa"),
    ("Crab apple", "Malus sylvestris"),
    ("Cypress, Lawson", "Chamaecyparis lawsoniana"),
    ("Cypress, Leyland", "Cupressus × leylandii"),
    ("Dogwood", "Cornus sanguinea"),
    ("Elder", "Sambucus nigra"),
    ("Elm, English", "Ulmus procera"),
    ("Elm, field", "Ulmus minor"),
    ("Elm, Huntingdon", "Ulmus × hollandica"),
    ("Elm, wych", "Ulmus glabra"),
    ("Eucalyptus", "Eucalyptus gunnii"),
    ("European larch", "Larix decidua"),
    ("Fir, Douglas", "Pseudotsuga menziesii"),
    ("Guelder rose", "Viburnum opulus"),
    ("Hawthorn", "Crataegus monogyna"),
    ("Hawthorn, Midland", "Crataegus laevigata"),
    ("Hazel", "Corylus avellana"),
    ("Hemlock, western", "Tsuga heterophylla"),
    ("Holly", "Ilex aquifolium"),
    ("Hornbeam", "Carpinus betulus"),
    ("Horse chestnut", "Aesculus hippocastanum"),
    ("Juniper", "Juniperus communis"),
    ("Lime, common", "Tilia × europaea"),
    ("Lime, large-leaved", "Tilia platyphyllos"),
    ("Lime, small-leaved", "Tilia cordata"),
    ("Maple, field", "Acer campestre"),
    ("Maple, Norway", "Acer platanoides"),
    ("Monkey puzzle", "Araucaria araucana"),
    ("Oak, English", "Quercus robur"),
    ("Oak, holm", "Quercus ilex"),
    ("Oak, red", "Quercus rubra"),
    ("Oak, sessile", "Quercus petraea"),
    ("Oak, Turkey", "Quercus cerris"),
    ("Pear", "Pyrus communis"),
    ("Pear, Plymouth", "Pyrus cordata"),
    ("Pine, black", "Pinus nigra"),
    ("Pine, Scots", "Pinus sylvestris"),
    ("Plane, London", "Platanus × hispanica"),
    ("Plum", "Prunus domestica"),
    ("Plum, cherry", "Prunus cerasifera"),
    ("Poplar, black", "Populus nigra"),
    ("Poplar, white", "Populus alba"),
    ("Rowan", "Sorbus aucuparia"),
    ("Spindle", "Euonymus europaeus"),
    ("Spruce, Norway", "Picea abies"),
    ("Spruce, Sitka", "Picea sitchensis"),
    ("Sycamore", "Acer pseudoplatanus"),
    ("Walnut", "Juglans regia"),
    ("Walnut, black", "Juglans nigra"),
    ("Wayfaring tree", "Viburnum lantana"),
    ("Western red cedar", "Thuja plicata"),
    ("Whitebeam", "Sorbus aria"),
    ("Whitebeam, Arran", "Sorbus arranensis"),
    ("Whitebeam, rock", "Sorbus rupicola"),
    ("Wild service tree", "Sorbus torminalis"),
    ("Willow, bay", "Salix pentandra"),
    ("Willow, crack", "Salix × fragilis"),
    ("Willow, goat", "Salix caprea"),
    ("Willow, grey", "Salix cinerea"),
    ("Willow, osier", "Salix viminalis"),
    ("Willow, white", "Salix alba"),
    ("Yew", "Taxus baccata"),
    ("Japanese larch (added)", "Larix kaempferi"),
    ("Japanese cherry (added)", "Prunus serrulata"),
]

GROUPS = [
    "Insecta",
    "Poaceae",
    "Anthocerotophyta",
    "Rhodophyta",
    "Chlorophyta",
    "Phaeophyceae",
    "Ulvophyceae",
    "Echinodermata",
    "Cnidaria",
    "Cirripedia",
    "Brachyura",
    "Polyplacophora",
    "Littorinidae",
    "Patellidae",
    "Mytilidae",
    "Cardiidae",
    "Trochidae",
    "Muricidae",
    "Homo sapiens",
    "Canis familiaris",
    "Felis catus",
    "Bos taurus",
    "Ovis aries",
    "Equus caballus",
    "Capra hircus",
    "Sus domesticus",
]


def resolve(name: str) -> dict:
    """Exact (or synonym) name match. A species can share its name with a "complex" taxon
    that contains it, so prefer species or hybrid rank, then the most observations."""
    r = throttled(
        "GET", f"{API}/taxa", params={"q": name, "is_active": "true", "per_page": 30}
    ).json()
    for how, key in (("exact", "name"), ("synonym", "matched_term")):
        matches = [t for t in r["results"] if (t.get(key) or "").lower() == name.lower()]
        if matches:
            t = max(
                matches,
                key=lambda t: (
                    t["rank"] in ("species", "hybrid"),
                    t.get("observations_count") or 0,
                ),
            )
            return {
                "id": t["id"],
                "name": t["name"],
                "rank": t["rank"],
                "how": how,
                "observations_count": t.get("observations_count"),
                "duplicates": [m["id"] for m in matches if m is not t],
            }
    return {
        "id": None,
        "candidates": [(t["id"], t["name"], t.get("matched_term")) for t in r["results"][:3]],
    }


def top(params: dict, n: int) -> list:
    base = {
        "place_id": 6857,
        "quality_grade": "research",
        "rank": "species",
        "locale": "en",
        "preferred_place_id": 6857,
        "per_page": n,
    }
    r = throttled("GET", f"{API}/observations/species_counts", params={**base, **params}).json()
    return [
        (x["taxon"]["id"], x["taxon"]["name"], x["taxon"].get("preferred_common_name"), x["count"])
        for x in r["results"]
    ]


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    groups = {name: resolve(name) for name in GROUPS}
    for k, v in groups.items():
        print("  group", k, v)
    trees = [(common, sci, resolve(sci)) for common, sci in TREES]
    for common, sci, v in trees:
        if v.get("how") != "exact":
            print("  TREE", common, sci, v)
    save("v2_groups", groups)
    save("v2_trees", trees)
    g = {k: v["id"] for k, v in groups.items()}

    ids = ",".join(str(v["id"]) for _, _, v in trees if v["id"])
    for captive in ("false", None):
        extra = {"taxon_id": ids, **({"captive": captive} if captive else {})}
        rows = [r for r in top(extra, 200) if r[0] in {v["id"] for _, _, v in trees}]
        print(f"  trees ranked (captive={captive}):", len(rows), rows[:8], "... last:", rows[45:50])
        save(f"v2_trees_ranked_captive_{captive}", rows)

    domestic = [
        "Homo sapiens",
        "Canis familiaris",
        "Felis catus",
        "Bos taurus",
        "Ovis aries",
        "Sus domesticus",
    ]
    print("  mammals captive=false:", top({"taxon_id": 40151, "captive": "false"}, 15))
    print(
        "  mammals minus domestic:",
        top(
            {
                "taxon_id": 40151,
                "captive": "false",
                "without_taxon_id": ",".join(str(g[d]) for d in domestic if g[d]),
            },
            12,
        ),
    )
    seashore = [
        "Phaeophyceae",
        "Rhodophyta",
        "Ulvophyceae",
        "Echinodermata",
        "Cnidaria",
        "Cirripedia",
        "Brachyura",
        "Polyplacophora",
        "Littorinidae",
        "Patellidae",
        "Mytilidae",
        "Cardiidae",
        "Trochidae",
        "Muricidae",
    ]
    print(
        "  seashore:",
        top({"taxon_id": ",".join(str(g[s]) for s in seashore if g[s]), "captive": "false"}, 25),
    )
    print("  insects:", top({"taxon_id": g["Insecta"], "captive": "false"}, 10))
    print("  grasses:", top({"taxon_id": g["Poaceae"], "captive": "false"}, 10))
    print("  liverworts:", top({"taxon_id": 64615, "captive": "false"}, 10))
    print("  hornworts:", top({"taxon_id": g["Anthocerotophyta"], "captive": "false"}, 5))
    print(
        "  plants minus mosses/liverworts/algae/grasses (top 10):",
        top(
            {
                "taxon_id": 47126,
                "captive": "false",
                "without_taxon_id": ",".join(
                    str(i)
                    for i in (
                        311249,
                        64615,
                        g["Anthocerotophyta"],
                        g["Rhodophyta"],
                        g["Chlorophyta"],
                        g["Poaceae"],
                    )
                    if i
                ),
            },
            10,
        ),
    )

    # Limits the spec depends on
    r = throttled(
        "GET",
        f"{API}/observations/species_counts",
        params={"place_id": 6857, "taxon_id": 47126, "per_page": 500},
    ).json()
    print("  species_counts per_page=500 returned", len(r["results"]))
    obs_ids = [o["id"] for o in json.loads((OUT / "user_observations.json").read_text())["results"]]
    r = throttled(
        "GET", f"{API}/observations", params={"id": ",".join(map(str, obs_ids)), "per_page": 200}
    ).json()
    print("  observations?id= with", len(obs_ids), "ids returned", len(r["results"]))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
