import pytest

from inat_anki.normalise import observation_from_api
from inat_anki.selection import choose_photos, inat_credit
from tests.conftest import load_fixture


@pytest.fixture
def cc_obs():
    return [observation_from_api(d) for d in load_fixture("v2_observations_cc.json")["results"]]


def choose(cc_obs, n=2, **kw):
    return choose_photos(cc_obs, n, "shareable", "me", "large", **kw)


def test_two_photos_from_different_observations_and_observers(cc_obs):
    chosen = choose(cc_obs)
    assert len(chosen) == 2
    assert chosen[0].source_id != chosen[1].source_id
    assert chosen[0].key == f"inat:{cc_obs[0].photos[0].id}"
    assert chosen[0].url.endswith("/large.jpg") or "/large." in chosen[0].url
    assert chosen[0].filename.startswith("inat_")


def test_prefers_new_observers_before_repeating(cc_obs):
    # Put two observations by the same observer first.
    same = [o for o in cc_obs if o.user_login == "observer_2"]
    others = [o for o in cc_obs if o.user_login != "observer_2"]
    chosen = choose(same + others)
    observers = {next(o for o in cc_obs if str(o.id) == c.source_id).user_login for c in chosen}
    assert len(observers) == 2


def test_falls_back_to_same_observer_when_needed(cc_obs):
    same = [o for o in cc_obs if o.user_login == "observer_2"]
    assert len(choose(same)) == 2


def test_mixed_licence_observation_keeps_only_usable(cc_obs):
    mixed = next(o for o in cc_obs if o.id == 900000101)
    chosen = choose([mixed], n=2)
    assert [c.key for c in chosen] == ["inat:900000105"]  # the NC photo is skipped


def test_reserved_only_observation_gives_nothing(cc_obs):
    arr = next(o for o in cc_obs if o.id == 900000103)
    assert choose([arr]) == []


def test_previous_choices_kept_when_still_usable(cc_obs):
    prev = cc_obs[3]  # observer_4, four photos
    key = f"inat:{prev.photos[2].id}"
    chosen = choose(cc_obs, previous=[key], previous_obs={str(prev.id): prev})
    assert chosen[0].key == key
    assert chosen[1].source_id != str(prev.id)


def test_previous_choice_replaced_when_licence_changes(cc_obs):
    prev = next(o for o in cc_obs if o.id == 900000101)
    chosen = choose(cc_obs, previous=["inat:900000102"], previous_obs={str(prev.id): prev})
    assert "inat:900000102" not in [c.key for c in chosen]
    assert len(chosen) == 2


def test_credit_links_licence_deed_and_observation(cc_obs):
    credit = inat_credit(cc_obs[1].photos[0], cc_obs[1])
    assert 'href="https://creativecommons.org/licenses/by/4.0/"' in credit
    assert f'href="https://www.inaturalist.org/observations/{cc_obs[1].id}"' in credit
    assert "Observer 2" in credit
