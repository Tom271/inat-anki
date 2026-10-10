import json
import re
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from inat_anki import media, species_state
from inat_anki.api import API_BASE, ApiError, INatClient
from inat_anki.commons import API as COMMONS_API
from inat_anki.commons import CommonsClient, user_agent
from inat_anki.model import ChosenPhoto, PhotoRecord, SetSpec
from inat_anki.sources import PlaceSpeciesSource
from inat_anki.state import StateError
from tests.conftest import load_fixture
from tests.fakes import FakeClock, fake_limiter

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 500


def query(call):
    return {k: v[0] for k, v in parse_qs(urlparse(call.request.url).query).items()}


@pytest.fixture
def client():
    return INatClient(fake_limiter(), "example_user")


@pytest.fixture
def source(client):
    return PlaceSpeciesSource(client, 6857)


@responses.activate
def test_ranked_query(source):
    responses.get(
        f"{API_BASE}/observations/species_counts", json=load_fixture("v2_species_counts.json")
    )
    spec = SetSpec(
        key="mammals",
        name="Mammals",
        count=10,
        taxon_ids=(40151,),
        without_taxon_ids=(43584, 47144),
    )
    rows = source.ranked(spec, [40151], 10)
    assert rows[0].taxon.name == "Erithacus rubecula"
    q = query(responses.calls[0])
    assert q == {
        "place_id": "6857",
        "quality_grade": "research",
        "rank": "species",
        "taxon_id": "40151",
        "without_taxon_id": "43584,47144",
        "locale": "en",
        "preferred_place_id": "6857",
        "per_page": "35",
    }


@responses.activate
def test_ranked_list_set_uses_hybrids_casual_and_full_page(source):
    responses.get(f"{API_BASE}/observations/species_counts", json={"results": []})
    spec = SetSpec(
        key="trees",
        name="Trees",
        count=50,
        species_list="x",
        quality_grade="research,casual",
        rank="species,hybrid",
    )
    source.ranked(spec, [1, 2, 3], 50)
    q = query(responses.calls[0])
    assert (q["rank"], q["quality_grade"], q["per_page"]) == (
        "species,hybrid",
        "research,casual",
        "500",
    )


@responses.activate
@pytest.mark.parametrize(
    ("fallback", "expected"),
    [
        (None, {"place_id": "6857", "quality_grade": "research"}),
        (
            "cultivated",
            {
                "place_id": "6857",
                "quality_grade": "casual",
                "captive": "true",
                "identifications": "most_agree",
            },
        ),
        ("world", {"quality_grade": "research"}),
    ],
)
def test_photo_candidate_queries(source, fallback, expected):
    responses.get(f"{API_BASE}/observations", json=load_fixture("v2_observations_cc.json"))
    obs = source.photo_candidates(12748, fallback)
    assert len(obs) == 7
    q = query(responses.calls[0])
    assert q["photo_license"] == "cc0,cc-by,cc-by-sa"
    for k, v in expected.items():
        assert q[k] == v
    if fallback == "world":
        assert "place_id" not in q


@responses.activate
def test_observations_by_id_batches_of_200(client):
    def callback(request):
        ids = query(type("C", (), {"request": request})())["id"].split(",")
        body = {"results": [{"id": int(i)} for i in ids]}
        return 200, {}, json.dumps(body)

    responses.add_callback(responses.GET, f"{API_BASE}/observations", callback)
    out = client.observations_by_id(list(range(1, 451)))
    assert [o["id"] for o in out] == list(range(1, 451))
    assert [int(query(c)["per_page"]) for c in responses.calls] == [200, 200, 50]


# ---------------------------------------------------------------- Commons


@pytest.fixture
def commons():
    http = INatClient(fake_limiter(), "example_user", agent=user_agent())
    return CommonsClient(http)


@responses.activate
def test_category_files(commons):
    responses.get(COMMONS_API, json=load_fixture("v2_commons_category.json"))
    files = commons.category_files("Hereford cattle")
    assert len(files) == 12
    q = query(responses.calls[0])
    assert q["gcmtitle"] == "Category:Hereford cattle"
    assert q["maxlag"] == "5" and q["iiurlwidth"] == "1024"
    agent = responses.calls[0].request.headers["User-Agent"]
    assert agent.startswith("inat-anki/") and "github.com/Tom271/inat-anki" in agent


@responses.activate
def test_maxlag_waits_and_retries():
    clock = FakeClock()
    http = INatClient(fake_limiter(clock=clock), "example_user", agent=user_agent())
    responses.get(COMMONS_API, json={"error": {"code": "maxlag", "info": "lagged"}})
    responses.get(COMMONS_API, json=load_fixture("v2_commons_category.json"))
    assert len(CommonsClient(http).search_files("Lleyn sheep")) == 12
    assert 5 in clock.sleeps
    assert query(responses.calls[1])["gsrsearch"] == '"Lleyn sheep"'


@responses.activate
def test_other_api_errors_raise(commons):
    responses.get(COMMONS_API, json={"error": {"code": "badvalue", "info": "nope"}})
    with pytest.raises(ApiError):
        commons.category_files("X")


@responses.activate
def test_file_info_handles_normalised_and_missing(commons):
    page = load_fixture("v2_commons_category.json")["query"]["pages"][0]
    responses.get(
        COMMONS_API,
        json={
            "query": {
                "normalized": [{"from": "File:a_b.jpg", "to": page["title"]}],
                "pages": [page, {"title": "File:Gone.jpg", "missing": True}],
            }
        },
    )
    info = commons.file_info(["File:a_b.jpg", "File:Gone.jpg"])
    assert list(info) == ["File:a_b.jpg"]


# ---------------------------------------------------------------- state and media


def test_species_state_round_trip(tmp_path):
    st = species_state.SpeciesState(
        source_key="place:6857:uk-common",
        photo_size="large",
        members={"birds": [12748], "farm-breeds": ["sheep/lleyn"]},
        counts={12748: 43195},
        taxa={
            12748: species_state.TaxonInfo(
                "Erithacus rubecula",
                "species",
                "European Robin",
                "Aves",
                "Passeriformes",
                "Muscicapidae",
            )
        },
        choices={"inat-place:6857:12748": [species_state.Choice("inat:1", "47813302")]},
        notes={"inat-place:6857:12748": "abc"},
        photos={"inat:1": PhotoRecord("inat_1.jpg", "large", 10, "cc0", "credit", "sha")},
    )
    path = tmp_path / "state.json"
    species_state.save(st, path)
    assert species_state.load(path) == st


def test_v1_state_file_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 1, "observations": {}}))
    with pytest.raises(StateError, match="separate --cache-dir"):
        species_state.load(path)


@responses.activate
def test_download_chosen(tmp_path, client):
    ok = ChosenPhoto(
        "commons:File:A.jpg",
        "commons_a.jpg",
        "https://upload.wikimedia.org/a.jpg",
        "credit A",
        "File:A.jpg",
        "cc-by-sa-4.0",
    )
    gone = ChosenPhoto(
        "inat:2", "inat_2.jpg", "https://static.example/2/large.jpg", "credit B", "2", "cc0"
    )
    responses.get(ok.url, body=JPEG)
    responses.get(gone.url, status=404)
    saved, failed = [], []
    media.download_chosen(
        client,
        [ok, gone],
        "large",
        tmp_path,
        1000,
        lambda p, r: saved.append(r),
        lambda p, e: failed.append(p.key),
    )
    assert saved == [
        PhotoRecord(
            "commons_a.jpg", "large", len(JPEG), "cc-by-sa-4.0", "credit A", media.sha256(JPEG)
        )
    ]
    assert failed == ["inat:2"]
    assert (tmp_path / "commons_a.jpg").read_bytes() == JPEG


@responses.activate
def test_download_chosen_aborts_on_server_error(tmp_path, client):
    p = ChosenPhoto("inat:3", "inat_3.jpg", "https://static.example/3/large.jpg", "c", "3")
    responses.get(re.compile(r"https://static\.example/.*"), status=503)
    with pytest.raises(ApiError):
        media.download_chosen(client, [p], "large", tmp_path, 1, lambda *a: None, lambda *a: None)
