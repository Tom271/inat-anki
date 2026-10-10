import pytest

from inat_anki.model import Photo
from inat_anki.normalise import media_filename, photo_ext, photo_url


def test_observation_fields(observations):
    obs = observations[125757925]
    assert obs.user_login == "example_user"
    assert obs.taxon.name == "Silene dioica"
    assert obs.taxon.common_name == "red campion"
    assert obs.taxon.rank == "species"
    assert obs.taxon.iconic_taxon_name == "Plantae"
    assert obs.time_observed_at == "2022-07-08T16:54:57+01:00"
    assert (obs.latitude, obs.longitude) == (52.8, -4.7)
    assert obs.accuracy_m == 8
    assert not obs.obscured
    assert obs.photos[0].license_code is None
    assert obs.photos[0].attribution == "(c) Example User, all rights reserved"


def test_photos_keep_api_order(observations):
    obs = observations[166402825]
    assert len(obs.photos) == 4
    assert len({p.id for p in obs.photos}) == 4


def test_missing_common_name_is_none(observations):
    assert observations[406515439].taxon.common_name is None


def test_obscured_uses_public_accuracy(observations):
    obs = observations[138594277]
    assert obs.obscured
    assert obs.accuracy_m == 25908


def test_no_location(edge_cases):
    obs = edge_cases[900000005]
    assert obs.latitude is None and obs.longitude is None
    assert obs.place_guess is None


def test_sound_only_has_no_photos(edge_cases):
    assert edge_cases[900000001].photos == ()


def test_ancestry(ancestries):
    assert ancestries[55759].order == "Caryophyllales"
    assert ancestries[55759].family == "Caryophyllaceae"
    assert ancestries[52195].family == "Caryophyllaceae"  # genus-level taxon


@pytest.mark.parametrize(
    ("url", "size", "expected"),
    [
        (
            "https://static.inaturalist.org/photos/211141858/square.jpeg",
            "large",
            "https://static.inaturalist.org/photos/211141858/large.jpeg",
        ),
        (
            "https://inaturalist-open-data.s3.amazonaws.com/photos/748281764/square.jpg",
            "medium",
            "https://inaturalist-open-data.s3.amazonaws.com/photos/748281764/medium.jpg",
        ),
    ],
)
def test_photo_url(url, size, expected):
    assert photo_url(Photo(1, url, None, ""), size) == expected


def test_photo_url_rejects_unknown_size():
    with pytest.raises(ValueError):
        photo_url(Photo(1, "https://x/photos/1/square.jpg", None, ""), "original")


@pytest.mark.parametrize(
    ("url", "ext"),
    [
        ("https://static.inaturalist.org/photos/1/square.jpeg", "jpeg"),
        ("https://static.inaturalist.org/photos/1/square.JPG", "jpg"),
        ("https://static.inaturalist.org/photos/1/square.png?1690000000", "png"),
        ("https://static.inaturalist.org/photos/1/square", "jpg"),
    ],
)
def test_photo_ext(url, ext):
    assert photo_ext(Photo(1, url, None, "")) == ext


def test_media_filename():
    photo = Photo(
        211141858, "https://static.inaturalist.org/photos/211141858/square.jpeg", None, ""
    )
    assert media_filename(photo) == "inat_211141858.jpeg"
