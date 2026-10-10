import json
from urllib.parse import parse_qs, urlparse

import responses

from inat_anki.api import API_BASE, INatClient
from tests.fakes import fake_limiter


def paged_observations(total: int):
    """A responses callback serving `total` observations, paged by id_above."""

    def callback(request):
        q = parse_qs(urlparse(request.url).query)
        assert q["order_by"] == ["id"] and q["order"] == ["asc"]
        assert "page" not in q
        id_above, per_page = int(q["id_above"][0]), int(q["per_page"][0])
        ids = [i for i in range(1, total + 1) if i > id_above][:per_page]
        body = {"total_results": total, "results": [{"id": i} for i in ids]}
        return 200, {}, json.dumps(body)

    return callback


@responses.activate
def test_paging_with_id_above_past_200():
    responses.add_callback(responses.GET, f"{API_BASE}/observations", paged_observations(450))
    client = INatClient(fake_limiter(), "example_user")
    ids = [o["id"] for o in client.iter_observations({"user_login": "example_user"})]
    assert ids == list(range(1, 451))
    assert len(responses.calls) == 3  # 200 + 200 + 50
    id_aboves = [parse_qs(urlparse(c.request.url).query)["id_above"][0] for c in responses.calls]
    assert id_aboves == ["0", "200", "400"]


@responses.activate
def test_small_account_is_one_request():
    responses.add_callback(responses.GET, f"{API_BASE}/observations", paged_observations(71))
    client = INatClient(fake_limiter(), "example_user")
    assert len(list(client.iter_observations({}))) == 71
    assert len(responses.calls) == 1


@responses.activate
def test_exact_multiple_of_page_size():
    responses.add_callback(responses.GET, f"{API_BASE}/observations", paged_observations(400))
    client = INatClient(fake_limiter(), "example_user")
    assert len(list(client.iter_observations({}))) == 400
    assert len(responses.calls) == 3  # the last page is empty


@responses.activate
def test_user_agent_header():
    responses.get(f"{API_BASE}/observations", json={"results": []})
    client = INatClient(fake_limiter(), "example_user")
    list(client.iter_observations({}))
    assert responses.calls[0].request.headers["User-Agent"] == "inat-anki/0.1.0 (example_user)"


@responses.activate
def test_taxa_batched_by_30():
    for start in (1, 31, 61):
        ids = ",".join(str(i) for i in range(start, min(start + 30, 66)))
        responses.get(
            f"{API_BASE}/taxa/{ids}",
            json={"results": [{"id": i} for i in range(start, min(start + 30, 66))]},
        )
    client = INatClient(fake_limiter(), "example_user")
    taxa = client.get_taxa(list(range(1, 66)), "en", 6857)
    assert [t["id"] for t in taxa] == list(range(1, 66))
    assert len(responses.calls) == 3
    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q == {"locale": ["en"], "preferred_place_id": ["6857"]}


@responses.activate
def test_download_records_bandwidth():
    url = "https://static.inaturalist.org/photos/1/large.jpeg"
    responses.get(url, body=b"\xff\xd8\xff" + b"x" * 997)
    limiter = fake_limiter()
    client = INatClient(limiter, "example_user")
    assert len(client.download(url, expected_bytes=250_000)) == 1000
    assert limiter.bandwidth.used(limiter.clock.time()) == 1000
