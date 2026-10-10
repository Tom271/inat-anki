"""Taxon ancestors via /v1/taxa/{ids} (SPEC 7.2).

Usage: uv run python scripts/verify_api_4.py <login>
"""

import json
import sys
from pathlib import Path

from verify_api import API, OUT, save, session, throttled


def main(login: str) -> None:
    session.headers["User-Agent"] = f"inat-anki/0.1.0 ({login})"
    obs = json.loads((OUT / "user_observations.json").read_text())["results"]
    ids = sorted({o["taxon"]["id"] for o in obs})
    print("  unique taxa", len(ids))
    r = throttled(
        "GET",
        f"{API}/taxa/{','.join(map(str, ids[:30]))}",
        params={"locale": "en", "preferred_place_id": 6857},
    ).json()
    save("taxa_show", r)
    print(
        "  returned",
        len(r["results"]),
        "of 30; has ancestors:",
        sum("ancestors" in t for t in r["results"]),
    )
    for t in r["results"][:5]:
        ranks = {a["rank"]: a["name"] for a in t.get("ancestors", [])}
        print("   ", t["name"], "| order:", ranks.get("order"), "| family:", ranks.get("family"))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1])
