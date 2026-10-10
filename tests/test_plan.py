from dataclasses import replace

import pytest

from inat_anki.model import ObsRecord, PhotoRecord
from inat_anki.normalise import media_filename
from inat_anki.plan import make_plan, split_ready
from inat_anki.render import note_hash, render

SOURCE = "user:example_user"


@pytest.fixture
def all_obs(observations, edge_cases):
    return list(observations.values()) + list(edge_cases.values())


def notes_for(obs_list, ancestries):
    return {o.id: render(o, ancestries.get(o.taxon.id), SOURCE) for o in obs_list if o.photos}


def synced_state(obs_list, notes, size="large"):
    """State as it would be after a complete previous run."""
    known_obs = {
        o.id: ObsRecord(o.updated_at, tuple(p.id for p in o.photos), note_hash(notes[o.id]))
        for o in obs_list
        if o.photos
    }
    known_photos = {
        p.id: PhotoRecord(media_filename(p), size, 500_000, p.license_code, p.attribution, "x")
        for o in obs_list
        for p in o.photos
    }
    return known_obs, known_photos


def plan_for(obs_list, ancestries, known_obs, known_photos, cached_ok=None, **kw):
    notes = notes_for(obs_list, ancestries)
    if cached_ok is None:
        cached_ok = set(known_photos)
    return make_plan(obs_list, notes, known_obs, known_photos, cached_ok, "large", **kw)


def test_first_run_everything_new(all_obs, ancestries):
    plan = plan_for(all_obs, ancestries, {}, {}, cached_ok=set())
    with_photos = [o for o in all_obs if o.photos]
    assert sorted(plan.new) == sorted(o.id for o in with_photos)
    assert plan.skipped_no_photos == [900000001]
    assert plan.changed == plan.unchanged == plan.removed == []
    unique_photos = {p.id for o in with_photos for p in o.photos}
    assert len(plan.downloads) == len(unique_photos)
    assert plan.estimated_bytes == len(unique_photos) * 250_000
    assert plan.estimated_seconds == len(unique_photos) * 1.0


def test_front_photos_downloaded_first(all_obs, ancestries):
    downloads = plan_for(all_obs, ancestries, {}, {}, cached_ok=set()).downloads
    flags = [d.is_front for d in downloads]
    assert flags == sorted(flags, reverse=True)
    assert flags.count(False) == 3  # the four-photo observation's extras


def test_second_run_unchanged_and_no_downloads(all_obs, ancestries):
    notes = notes_for(all_obs, ancestries)
    known_obs, known_photos = synced_state(all_obs, notes)
    plan = plan_for(all_obs, ancestries, known_obs, known_photos)
    assert plan.new == plan.changed == plan.removed == []
    assert len(plan.unchanged) == len(known_obs)
    assert plan.downloads == []
    assert plan.estimated_bytes == 0


def test_new_observation(observations, ancestries):
    obs_list = list(observations.values())
    earlier = [o for o in obs_list if o.id != 406802316]
    known_obs, known_photos = synced_state(earlier, notes_for(earlier, ancestries))
    plan = plan_for(obs_list, ancestries, known_obs, known_photos)
    assert plan.new == [406802316]
    assert [d.obs_id for d in plan.downloads] == [406802316]


def test_changed_taxon(observations, ancestries):
    obs_list = list(observations.values())
    known_obs, known_photos = synced_state(obs_list, notes_for(obs_list, ancestries))
    target = observations[125757925]
    new_taxon = replace(
        target.taxon, id=55760, name="Silene latifolia", common_name="white campion"
    )
    obs_list = [replace(o, taxon=new_taxon) if o.id == target.id else o for o in obs_list]
    plan = plan_for(obs_list, ancestries, known_obs, known_photos)
    assert plan.changed == [125757925]
    assert plan.downloads == []


def test_removed_when_no_longer_research_grade(observations, ancestries):
    obs_list = list(observations.values())
    known_obs, known_photos = synced_state(obs_list, notes_for(obs_list, ancestries))
    lost = observations[405770862]
    remaining = [o for o in obs_list if o.id != lost.id]
    plan = plan_for(remaining, ancestries, known_obs, known_photos)
    assert plan.removed == [lost.id]
    assert plan.unreferenced_photos == [p.id for p in lost.photos]


def test_missing_or_corrupt_photo_redownloaded(observations, ancestries):
    obs_list = list(observations.values())
    known_obs, known_photos = synced_state(obs_list, notes_for(obs_list, ancestries))
    missing = observations[125757925].photos[0].id  # file deleted
    corrupt = observations[403884245].photos[0].id  # sha256 mismatch
    # Both kinds arrive as "not in cached_ok": media.scan_cache checks existence and hash.
    cached_ok = set(known_photos) - {missing, corrupt}
    plan = plan_for(obs_list, ancestries, known_obs, known_photos, cached_ok=cached_ok)
    assert sorted(d.photo_id for d in plan.downloads) == sorted([missing, corrupt])
    assert plan.new == plan.changed == []


def test_size_change_redownloads(observations, ancestries):
    obs_list = list(observations.values())
    known_obs, known_photos = synced_state(obs_list, notes_for(obs_list, ancestries), size="medium")
    plan = plan_for(obs_list, ancestries, known_obs, known_photos)
    assert len(plan.downloads) == len(known_photos)
    assert all("/large." in d.url for d in plan.downloads)


def test_refresh_redownloads_everything(observations, ancestries):
    obs_list = list(observations.values())
    known_obs, known_photos = synced_state(obs_list, notes_for(obs_list, ancestries))
    plan = plan_for(obs_list, ancestries, known_obs, known_photos, refresh=True)
    assert len(plan.downloads) == len(known_photos)
    assert plan.new == plan.changed == []


def test_estimate_uses_cached_sizes(observations, ancestries):
    obs_list = list(observations.values())
    known_obs, known_photos = synced_state(obs_list, notes_for(obs_list, ancestries))
    plan = plan_for(
        obs_list, ancestries, known_obs, known_photos, cached_ok=set(), min_interval=1.5
    )
    assert plan.estimated_bytes == len(plan.downloads) * 500_000
    assert plan.estimated_seconds == len(plan.downloads) * 1.5


def test_split_ready_defers_missing_front_photo(observations, ancestries):
    notes = notes_for(observations.values(), ancestries)
    available = {n.front_media for n in notes.values()} - {notes[125757925].front_media}
    ready, deferred = split_ready(notes, available)
    assert deferred == [125757925]
    assert len(ready) == len(notes) - 1
