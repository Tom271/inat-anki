import json

import pytest
import responses

from inat_anki import media, state
from inat_anki.api import ApiError, INatClient
from inat_anki.model import ObsRecord, Photo, PhotoDownload, PhotoRecord, TaxonAncestry
from inat_anki.throttle import BandwidthWindow, DailyCounter
from tests.fakes import fake_limiter

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes" * 10


def test_state_round_trip(tmp_path):
    s = state.State(
        source_key="user:example_user",
        photo_size="large",
        observations={1: ObsRecord("2024-01-01T00:00:00+00:00", (10, 11), "abc")},
        photos={10: PhotoRecord("inat_10.jpg", "large", 123, None, "(c) X", "d" * 64)},
        taxa={5: TaxonAncestry(5, "Fabales", None)},
        requests=DailyCounter(day="2026-10-10", count=4),
        downloads=BandwidthWindow(entries=[(1.5, 123)]),
    )
    path = tmp_path / "state.json"
    state.save(s, path)
    assert json.loads(path.read_text())["schema_version"] == 1
    loaded = state.load(path)
    assert loaded.observations == s.observations
    assert loaded.photos == s.photos
    assert loaded.taxa == s.taxa
    assert (loaded.requests.day, loaded.requests.count) == ("2026-10-10", 4)
    assert loaded.downloads.entries == [(1.5, 123)]
    assert (loaded.source_key, loaded.photo_size) == ("user:example_user", "large")


def test_missing_state_is_empty(tmp_path):
    assert state.load(tmp_path / "nope.json") == state.State()


def test_wrong_schema_version_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 2}))
    with pytest.raises(state.StateError):
        state.load(path)


def test_corrupt_state_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(state.StateError):
        state.load(path)


def test_atomic_write_leaves_no_temp_files(tmp_path):
    state.write_atomic(tmp_path / "a.bin", b"one")
    state.write_atomic(tmp_path / "a.bin", b"two")
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]
    assert (tmp_path / "a.bin").read_bytes() == b"two"


def record_for(name: str, data: bytes) -> PhotoRecord:
    return PhotoRecord(name, "large", len(data), None, "", media.sha256(data))


def test_scan_cache_detects_missing_and_corrupt(tmp_path):
    (tmp_path / "inat_1.jpg").write_bytes(JPEG)
    (tmp_path / "inat_2.jpg").write_bytes(JPEG)
    (tmp_path / "inat_3.jpg").write_bytes(JPEG[:-1] + b"!")  # same size, wrong sha256
    (tmp_path / "inat_4.jpg").write_bytes(JPEG[:10])  # truncated
    records = {i: record_for(f"inat_{i}.jpg", JPEG) for i in range(1, 6)}  # 5 is missing
    assert media.scan_cache(tmp_path, records) == {1, 2}


def photo(i: int) -> Photo:
    return Photo(i, f"https://static.inaturalist.org/photos/{i}/square.jpg", None, "(c) X")


def download(i: int) -> PhotoDownload:
    return PhotoDownload(
        i, 100, f"https://static.inaturalist.org/photos/{i}/large.jpg", f"inat_{i}.jpg", True
    )


@responses.activate
def test_download_all_saves_each_photo_and_skips_bad_ones(tmp_path):
    responses.get(download(1).url, body=JPEG)
    responses.get(download(2).url, status=404)
    responses.get(download(3).url, body=b"<html>not an image</html>")
    responses.get(download(4).url, body=JPEG)
    client = INatClient(fake_limiter(), "example_user")
    saved, failed = [], []
    media.download_all(
        client,
        [download(i) for i in range(1, 5)],
        {i: photo(i) for i in range(1, 5)},
        "large",
        tmp_path,
        250_000,
        on_saved=lambda d, r: saved.append((d.photo_id, r)),
        on_failed=lambda d, e: failed.append(d.photo_id),
    )
    assert [i for i, _ in saved] == [1, 4]
    assert failed == [2, 3]
    assert saved[0][1] == PhotoRecord(
        "inat_1.jpg", "large", len(JPEG), None, "(c) X", media.sha256(JPEG)
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["inat_1.jpg", "inat_4.jpg"]


@responses.activate
def test_download_all_aborts_on_persistent_server_error(tmp_path):
    responses.get(download(1).url, status=503)
    client = INatClient(fake_limiter(), "example_user")
    with pytest.raises(ApiError):
        media.download_all(
            client,
            [download(1)],
            {1: photo(1)},
            "large",
            tmp_path,
            1,
            on_saved=lambda d, r: None,
            on_failed=lambda d, e: None,
        )


@responses.activate
def test_interruption_keeps_completed_photos(tmp_path):
    responses.get(download(1).url, body=JPEG)
    responses.get(download(2).url, body=JPEG)
    client = INatClient(fake_limiter(), "example_user")
    saved = []

    def on_saved(d, r):
        saved.append(d.photo_id)
        if len(saved) == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        media.download_all(
            client,
            [download(1), download(2)],
            {1: photo(1), 2: photo(2)},
            "large",
            tmp_path,
            1,
            on_saved=on_saved,
            on_failed=lambda d, e: None,
        )
    assert [p.name for p in tmp_path.iterdir()] == ["inat_1.jpg"]


def test_prune(tmp_path):
    (tmp_path / "inat_1.jpg").write_bytes(JPEG)
    assert media.prune(tmp_path, ["inat_1.jpg", "inat_2.jpg"]) == len(JPEG)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("data", "ok"),
    [
        (JPEG, True),
        (b"\x89PNG\r\n\x1a\n" + b"x", True),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", True),
        (b"<html>", False),
        (b"", False),
    ],
)
def test_looks_like_image(data, ok):
    assert media.looks_like_image(data) is ok
