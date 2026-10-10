import json
import re
import sqlite3
import zipfile

import pytest
import responses

from inat_anki import cli, state
from inat_anki.api import API_BASE
from tests.conftest import load_fixture
from tests.fakes import FakeClock

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 1000
OBS = load_fixture("observations_page.json")
EDGE = load_fixture("observations_edge_cases.json")
TAXA = load_fixture("taxa.json")
PHOTO_RE = re.compile(r"https://static\.inaturalist\.org/photos/\d+/large\.jpe?g")


def all_observations():
    return OBS["results"] + EDGE["results"]


def split_off_last():
    """All observations, and the same without the last real one (whose photos no edge case
    shares; the edge cases are copies of the first observation)."""
    obs = all_observations()
    last = OBS["results"][-1]
    return obs, [o for o in obs if o["id"] != last["id"]], last


def settings(tmp_path, **overrides):
    s = {
        **cli.DEFAULTS,
        "user": "example_user",
        "cache_dir": str(tmp_path / "cache"),
        "out": str(tmp_path / "deck.apkg"),
        **overrides,
    }
    s["interval"] = cli.interval_for_rate(s["rate"])
    return s


def mock_api(observations):
    responses.get(
        f"{API_BASE}/observations",
        json={"total_results": len(observations), "results": observations},
    )
    responses.get(re.compile(rf"{API_BASE}/taxa/[\d,]+"), json=TAXA)
    responses.get(PHOTO_RE, body=JPEG)


def run(tmp_path, clock=None, **overrides):
    lines = []
    code = cli.sync(
        settings(tmp_path, **overrides),
        clock=clock or FakeClock(),
        ask=lambda prompt: "n",
        out=lines.append,
    )
    return code, lines


def calls(kind):
    pattern = {"api": API_BASE, "photo": "static.inaturalist.org"}[kind]
    return [
        c
        for c in responses.calls
        if c.request.url.startswith(f"https://{pattern}") or c.request.url.startswith(pattern)
    ]


def notes_in(apkg, tmp_path):
    with zipfile.ZipFile(apkg) as z:
        z.extract("collection.anki2", tmp_path / "x")
    db = sqlite3.connect(tmp_path / "x" / "collection.anki2")
    return {int(r[0]) for r in db.execute("select sfld from notes")}


def with_photos(observations):
    return {o["id"] for o in observations if o["photos"]}


def unique_photo_count(observations):
    return len({p["id"] for o in observations for p in o["photos"]})


@responses.activate
def test_first_run_then_second_run_downloads_nothing(tmp_path):
    obs = all_observations()
    mock_api(obs)
    code, lines = run(tmp_path)
    assert code == 0
    assert len(calls("photo")) == unique_photo_count(obs)
    assert notes_in(tmp_path / "deck.apkg", tmp_path) == with_photos(obs)
    report = json.loads((tmp_path / "cache" / "last-run.json").read_text())
    assert report["new"] == len(with_photos(obs))
    assert report["skipped"] == [{"obs_id": 900000001, "reason": "no photos"}]

    responses.calls.reset()
    code, lines = run(tmp_path)
    assert code == 0
    assert calls("photo") == []
    assert len(calls("api")) == 1  # observations only; taxa are cached
    report = json.loads((tmp_path / "cache" / "last-run.json").read_text())
    assert (report["new"], report["changed"]) == (0, 0)
    assert report["unchanged"] == len(with_photos(obs))
    assert notes_in(tmp_path / "deck.apkg", tmp_path / "y") == with_photos(obs)


@responses.activate
def test_new_observation_downloads_only_its_photos(tmp_path):
    obs, earlier, latest = split_off_last()
    mock_api(earlier)
    run(tmp_path)
    responses.reset()
    mock_api(obs)
    code, _ = run(tmp_path)
    assert code == 0
    assert len(calls("photo")) == len(latest["photos"])
    report = json.loads((tmp_path / "cache" / "last-run.json").read_text())
    assert report["new"] == 1


@responses.activate
def test_removed_observation_reported_with_search(tmp_path):
    obs, remaining, lost = split_off_last()
    mock_api(obs)
    run(tmp_path)
    responses.reset()
    gone = lost["id"]
    mock_api(remaining)
    code, lines = run(tmp_path)
    report = json.loads((tmp_path / "cache" / "last-run.json").read_text())
    assert report["removed"] == [gone]
    assert f"ObsID:{gone}" in report["removed_search"]
    assert gone not in notes_in(tmp_path / "deck.apkg", tmp_path)
    # Photos are kept unless --prune.
    st = state.load(tmp_path / "cache" / "state.json")
    assert lost["photos"][0]["id"] in st.photos


@responses.activate
def test_prune_deletes_unreferenced_photos(tmp_path):
    obs, remaining, lost = split_off_last()
    mock_api(obs)
    run(tmp_path)
    responses.reset()
    mock_api(remaining)
    run(tmp_path, prune=True)
    st = state.load(tmp_path / "cache" / "state.json")
    photo_id = lost["photos"][0]["id"]
    assert photo_id not in st.photos
    assert not list((tmp_path / "cache" / "media").glob(f"inat_{photo_id}.*"))


@responses.activate
def test_dry_run_downloads_nothing_and_writes_no_deck(tmp_path):
    mock_api(all_observations())
    code, lines = run(tmp_path, dry_run=True)
    assert code == 0
    assert calls("photo") == []
    assert not (tmp_path / "deck.apkg").exists()
    assert any("photos to download" in line for line in lines)


@responses.activate
def test_max_downloads_defers_and_resumes(tmp_path):
    obs = OBS["results"]
    mock_api(obs)
    code, _ = run(tmp_path, max_downloads=3)
    assert code == 0
    assert len(calls("photo")) == 3
    report = json.loads((tmp_path / "cache" / "last-run.json").read_text())
    deferred = [s for s in report["skipped"] if s["reason"].startswith("front photo")]
    assert len(deferred) == len(obs) - 3
    assert report["notes_in_deck"] == 3

    responses.calls.reset()
    run(tmp_path)
    assert len(calls("photo")) == unique_photo_count(obs) - 3
    assert notes_in(tmp_path / "deck.apkg", tmp_path) == with_photos(obs)


@responses.activate
def test_partial_extras_are_rebuilt_next_run(tmp_path):
    obs = [o for o in OBS["results"] if len(o["photos"]) == 4]
    mock_api(obs)
    run(tmp_path, max_downloads=2)  # front + one extra
    st = state.load(tmp_path / "cache" / "state.json")
    assert st.observations[obs[0]["id"]].note_hash == ""
    run(tmp_path)
    report = json.loads((tmp_path / "cache" / "last-run.json").read_text())
    assert report["changed"] == 1
    st = state.load(tmp_path / "cache" / "state.json")
    assert st.observations[obs[0]["id"]].note_hash != ""


@responses.activate
def test_large_run_asks_and_can_be_cancelled(tmp_path):
    mock_api(all_observations())
    code, lines = run(tmp_path, warn_threshold=2)
    assert code == 1
    assert "Cancelled." in lines
    assert calls("photo") == []


@responses.activate
def test_changed_only_writes_just_new_and_changed(tmp_path):
    obs, earlier, latest = split_off_last()
    mock_api(earlier)
    run(tmp_path)
    responses.reset()
    mock_api(obs)
    run(tmp_path, changed_only=True)
    assert notes_in(tmp_path / "deck.apkg", tmp_path) == {latest["id"]}


@responses.activate
def test_cache_belongs_to_one_user(tmp_path):
    mock_api(all_observations())
    run(tmp_path)
    with pytest.raises(cli.UsageError):
        run(tmp_path, user="someone_else")


@responses.activate
def test_server_error_exits_cleanly(tmp_path):
    responses.get(f"{API_BASE}/observations", status=500)
    code, lines = run(tmp_path)
    assert code == 1
    assert any(line.startswith("Error:") for line in lines)


def test_config_file_and_flag_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inat-anki.toml").write_text('user = "from_file"\nphoto-size = "medium"\n')
    args = cli.build_parser().parse_args(["sync", "--photo-size", "large"])
    s = cli.resolve_settings(args)
    assert (s["user"], s["photo_size"]) == ("from_file", "large")


def test_config_unknown_key_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inat-anki.toml").write_text('usr = "typo"\n')
    with pytest.raises(cli.UsageError):
        cli.resolve_settings(cli.build_parser().parse_args(["sync"]))


def test_rate_above_limit_rejected():
    args = cli.build_parser().parse_args(["sync", "--user", "x", "--rate", "2"])
    with pytest.raises(cli.UsageError):
        cli.resolve_settings(args)


def test_missing_user_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(cli.UsageError):
        cli.resolve_settings(cli.build_parser().parse_args(["sync"]))
