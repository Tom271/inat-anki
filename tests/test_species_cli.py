import json
import re
import sqlite3
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from inat_anki import cli
from inat_anki.api import API_BASE
from inat_anki.commons import API as COMMONS_API
from inat_anki.species_sync import species
from tests.conftest import load_fixture
from tests.fakes import FakeClock

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 800
COUNTS = load_fixture("v2_species_counts.json")
CC_OBS = load_fixture("v2_observations_cc.json")
USER_OBS = load_fixture("observations_page.json")
COMMONS = load_fixture("v2_commons_category.json")
SEEN_BIRD = 13094  # pretend the user has observed the robin

SETS = """
place_id = 6857
deck = "iNaturalist::UK common species"
photos_per_species = 2
seen_by = "example_user"

[[set]]
key = "birds"
name = "Birds"
taxon_id = [3]
count = 2

[[set]]
key = "farm"
name = "Farm breeds"
breed_list = "breeds.toml"
"""
BREEDS = """
[[breed]]
key = "cattle/hereford"
name = "Hereford"
species = "Bos taurus"
taxon_id = 74113
commons_category = "Hereford cattle"
wikipedia = "Hereford cattle"
"""


def q(request):
    return {k: v[0] for k, v in parse_qs(urlparse(request.url).query).items()}


def mock_all(counts=COUNTS):
    def observations(request):
        params = q(request)
        if "user_login" in params:
            obs = json.loads(json.dumps(USER_OBS["results"]))
            obs[0]["taxon"]["ancestor_ids"] = [3, SEEN_BIRD]
            return 200, {}, json.dumps({"results": obs})
        if "id" in params:
            ids = set(params["id"].split(","))
            return (
                200,
                {},
                json.dumps({"results": [o for o in CC_OBS["results"] if str(o["id"]) in ids]}),
            )
        # Photo search: a different first observation per species, as in real data.
        k = int(params["taxon_id"]) % 5
        results = CC_OBS["results"][k:5] + CC_OBS["results"][:k] + CC_OBS["results"][5:]
        return 200, {}, json.dumps({"results": results})

    def taxa(request):
        ids = urlparse(request.url).path.rsplit("/", 1)[1].split(",")
        return (
            200,
            {},
            json.dumps(
                {
                    "results": [
                        {
                            "id": int(i),
                            "name": f"Taxon {i}",
                            "rank": "species",
                            "ancestors": [
                                {"id": 1, "rank": "order", "name": "Passeriformes"},
                                {"id": 2, "rank": "family", "name": "Muscicapidae"},
                            ],
                        }
                        for i in ids
                    ]
                }
            ),
        )

    def commons(request):
        params = q(request)
        if "titles" in params:
            titles = set(params["titles"].split("|"))
            pages = [p for p in COMMONS["query"]["pages"] if p["title"] in titles]
            return 200, {}, json.dumps({"query": {"pages": pages}})
        return 200, {}, json.dumps(COMMONS)

    responses.add_callback(responses.GET, f"{API_BASE}/observations", observations)
    responses.get(f"{API_BASE}/observations/species_counts", json=counts)
    responses.add_callback(responses.GET, re.compile(rf"{API_BASE}/taxa/[\d,]+"), taxa)
    responses.add_callback(responses.GET, COMMONS_API, commons)
    responses.get(
        re.compile(r"https://(inaturalist-open-data|upload\.wikimedia|thumb\.wikimedia)\S+"),
        body=JPEG,
    )


@pytest.fixture
def sets_file(tmp_path):
    (tmp_path / "breeds.toml").write_text(BREEDS)
    path = tmp_path / "uk-common.toml"
    path.write_text(SETS)
    return path


def settings(tmp_path, sets_file, **kw):
    s = {
        **cli.SPECIES_DEFAULTS,
        "sets": str(sets_file),
        "cache_dir": str(tmp_path / "cache"),
        "out": str(tmp_path / "species.apkg"),
        **kw,
    }
    s["interval"] = cli.interval_for_rate(s["rate"])
    return s


def run(tmp_path, sets_file, **kw):
    lines = []
    code = species(
        settings(tmp_path, sets_file, **kw), clock=FakeClock(), ask=lambda p: "n", out=lines.append
    )
    path = tmp_path / "cache" / "last-run.json"
    report = json.loads(path.read_text()) if path.exists() else None
    return code, report, lines


def downloads():
    return [
        c
        for c in responses.calls
        if "inaturalist-open-data" in c.request.url or "wikimedia.org/wikipedia" in c.request.url
    ]


def notes(tmp_path, name="species.apkg"):
    with zipfile.ZipFile(tmp_path / name) as z:
        z.extract("collection.anki2", tmp_path / "x")
    db = sqlite3.connect(tmp_path / "x" / "collection.anki2")
    rows = db.execute("select flds, tags from notes").fetchall()
    decks = json.loads(db.execute("select decks from col").fetchone()[0])
    (tmp_path / "x" / "collection.anki2").unlink()
    return rows, {d["name"] for d in decks.values()}


@responses.activate
def test_first_and_second_build(tmp_path, sets_file):
    mock_all()
    code, report, _ = run(tmp_path, sets_file)
    assert code == 0
    assert report["sets"]["birds"]["members"] == 2
    assert report["sets"]["farm"]["members"] == 1
    assert report["sets"]["birds"]["seen"] == 1
    assert report["unreviewed_breeds"] == ["cattle/hereford"]
    st = json.loads((tmp_path / "cache" / "state.json").read_text())
    assert len(downloads()) == len(st["photos"]) >= 5  # 2 birds x 2 + 1 breed x 2, deduped
    assert all(len(v) == 2 for v in st["choices"].values())
    rows, decks = notes(tmp_path)
    assert len(rows) == 3
    assert {
        "iNaturalist::UK common species::Birds",
        "iNaturalist::UK common species::Farm breeds",
    } <= decks
    tags = " ".join(t for _, t in rows)
    assert "inat::seen" in tags and "breed::cattle" in tags
    assert set(report["licences"]) <= {
        "cc0",
        "cc-by",
        "cc-by-sa",
        "cc-by-sa-3.0",
        "cc-by-sa-4.0",
        "cc-by-2.0",
        "pd",
    }

    responses.calls.reset()
    code, report, _ = run(tmp_path, sets_file)
    assert code == 0
    assert downloads() == []
    # user observations, ranking, licence re-check, Commons re-check
    assert len(responses.calls) == 4
    assert report["sets"]["birds"]["added"] == 0
    assert len(notes(tmp_path)[0]) == 3


@responses.activate
def test_dry_run_downloads_nothing(tmp_path, sets_file):
    mock_all()
    code, report, lines = run(tmp_path, sets_file, dry_run=True)
    assert code == 0 and downloads() == []
    assert not (tmp_path / "species.apkg").exists()
    assert any("photos to download" in line for line in lines)


@responses.activate
def test_membership_is_sticky_until_rerank(tmp_path, sets_file):
    mock_all()
    run(tmp_path, sets_file)
    first = [r["taxon"]["id"] for r in COUNTS["results"][:2]]
    responses.reset()
    reordered = {**COUNTS, "results": COUNTS["results"][2:] + COUNTS["results"][:2]}
    mock_all(counts=reordered)
    _, report, _ = run(tmp_path, sets_file)
    assert report["sets"]["birds"]["members"] == 2
    assert sorted(report["sets"]["birds"]["below_cutoff"]) == sorted(first)
    _, report, _ = run(tmp_path, sets_file, rerank=True)
    assert sorted(r["taxon_id"] for r in report["removed"]) == sorted(first)
    assert "TaxonID:" in report["removed_search"]


@responses.activate
def test_only_builds_named_sets(tmp_path, sets_file):
    mock_all()
    code, report, _ = run(tmp_path, sets_file, only="farm")
    assert code == 0
    assert list(report["sets"]) == ["farm"]
    rows, decks = notes(tmp_path)
    assert len(rows) == 1
    assert "iNaturalist::UK common species::Birds" not in decks


@responses.activate
def test_seen_by_can_be_turned_off(tmp_path, sets_file):
    mock_all()
    _, report, _ = run(tmp_path, sets_file, seen_by="")
    assert report["sets"]["birds"]["seen"] == 0
    assert not any("user_login" in c.request.url for c in responses.calls)


@responses.activate
def test_suggest_breed_photos_writes_review_page(tmp_path, sets_file):
    mock_all()
    code, _, lines = run(tmp_path, sets_file, suggest_breed_photos=True)
    assert code == 0
    page = (tmp_path / "cache" / "breed-photos.html").read_text()
    assert "Hereford" in page and "Wikimedia Commons" in page and "<img" in page
    assert downloads() == []


def test_unknown_only_set_rejected(tmp_path, sets_file):
    with pytest.raises(Exception, match="unknown set"):
        species(settings(tmp_path, sets_file, only="nope"), clock=FakeClock())


def test_cli_parses_species():
    args = cli.build_parser().parse_args(["species", "--only", "birds", "--dry-run"])
    s = cli.resolve_species_settings(args)
    assert (s["only"], s["dry_run"], s["cache_dir"]) == ("birds", True, "inat-cache-species")
