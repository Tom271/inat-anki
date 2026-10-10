from dataclasses import replace

import pytest

from inat_anki.model import FIELD_NAMES, Photo
from inat_anki.render import anki_search, format_observed, note_hash, photo_credit, render

SOURCE = "user:example_user"


def note_for(obs, ancestries):
    return render(obs, ancestries.get(obs.taxon.id), SOURCE)


def test_fields_in_order(observations, ancestries):
    note = note_for(observations[125757925], ancestries)
    assert len(note.fields) == len(FIELD_NAMES)
    assert note.field("ObsID") == "125757925"
    assert note.field("CommonName") == "red campion"
    assert note.field("ScientificName") == "Silene dioica"
    assert note.field("Rank") == ""
    assert note.field("ObservedOn") == "Fri 8 Jul 2022, 16:54"
    assert note.field("Place") == "Example Park, Exampleton, England, GB"
    assert note.field("Coordinates") == "52.80000, -4.70000 (±8 m)"
    assert note.field("ObsURL") == "https://www.inaturalist.org/observations/125757925"
    assert note.field("TaxonID") == "55759"
    assert note.field("Source") == SOURCE
    assert note.field("PhotoCredits") == "(c) Example User, all rights reserved"


def test_front_and_extra_photos(observations, ancestries):
    obs = observations[166402825]
    note = note_for(obs, ancestries)
    ids = [p.id for p in obs.photos]
    assert note.field("FrontPhoto") == f'<img src="inat_{ids[0]}.jpeg">'
    assert note.field("ExtraPhotos") == "".join(f'<img src="inat_{i}.jpeg">' for i in ids[1:])
    assert note.front_media == f"inat_{ids[0]}.jpeg"
    assert note.media == tuple(f"inat_{i}.jpeg" for i in ids)
    assert note.field("PhotoCredits").count("<br>") == 3


def test_no_common_name(observations, ancestries):
    note = note_for(observations[406515439], ancestries)
    assert note.field("CommonName") == ""
    assert note.field("ScientificName") == "Cirsium monspessulanum"


def test_genus_level_shows_rank(edge_cases, ancestries):
    note = note_for(edge_cases[900000003], ancestries)
    assert note.field("ScientificName") == "Silene"
    assert note.field("Rank") == "genus"


def test_subspecies_shows_rank(observations, ancestries):
    assert note_for(observations[405419599], ancestries).field("Rank") == "subspecies"


def test_obscured_location(observations, ancestries):
    note = note_for(observations[138594277], ancestries)
    assert note.field("Place") == "England, GB (location obscured)"
    assert note.field("Coordinates") == ""


def test_obscured_without_place(observations):
    obs = replace(observations[138594277], place_guess=None)
    assert render(obs, None, SOURCE).field("Place") == "(location obscured)"


def test_no_location(edge_cases):
    note = render(edge_cases[900000005], None, SOURCE)
    assert note.field("Place") == ""
    assert note.field("Coordinates") == ""


def test_no_time_shows_date_only(edge_cases):
    assert render(edge_cases[900000002], None, SOURCE).field("ObservedOn") == "Fri 8 Jul 2022"


def test_no_date_at_all(edge_cases):
    obs = replace(edge_cases[900000002], observed_on=None)
    assert render(obs, None, SOURCE).field("ObservedOn") == ""


@pytest.mark.parametrize(
    ("time_observed_at", "expected"),
    [
        ("2024-05-04T14:32:00+01:00", "Sat 4 May 2024, 14:32"),  # BST stays local
        ("2024-12-25T09:05:00+00:00", "Wed 25 Dec 2024, 09:05"),
        ("2022-08-31T11:36:39+03:00", "Wed 31 Aug 2022, 11:36"),  # Athens, not converted
        ("2024-01-01T00:15:00-05:00", "Mon 1 Jan 2024, 00:15"),
    ],
)
def test_british_date_format(edge_cases, time_observed_at, expected):
    obs = replace(edge_cases[900000002], time_observed_at=time_observed_at)
    assert format_observed(obs) == expected


def test_html_escaping_of_place(edge_cases):
    place = render(edge_cases[900000004], None, SOURCE).field("Place")
    assert place == (
        "Fish &amp; Chips &lt;b&gt;&quot;Shop&quot;&lt;/b&gt; &lt;script&gt;x&lt;/script&gt;"
    )


def test_render_rejects_observation_without_photos(edge_cases):
    with pytest.raises(ValueError):
        render(edge_cases[900000001], None, SOURCE)


def test_tags(observations, ancestries):
    note = note_for(observations[125757925], ancestries)
    assert note.tags == (
        "inat::iconic::Plantae",
        "inat::order::Caryophyllales",
        "inat::family::Caryophyllaceae",
        "inat::user::example_user",
    )


def test_tags_without_ancestry(observations):
    assert render(observations[125757925], None, SOURCE).tags == (
        "inat::iconic::Plantae",
        "inat::user::example_user",
    )


@pytest.mark.parametrize(
    ("photo", "credit"),
    [
        (
            Photo(1, "u", None, "(c) Example User, all rights reserved"),
            "(c) Example User, all rights reserved",
        ),
        (
            Photo(1, "u", "cc-by", "(c) A. Person, some rights reserved (CC BY)"),
            "(c) A. Person, some rights reserved (CC BY)",
        ),
        (Photo(1, "u", "cc-by-nc", "(c) A. Person"), "(c) A. Person (CC BY-NC)"),
        (Photo(1, "u", None, ""), "All rights reserved"),
        (Photo(1, "u", "cc0", "<b>Me</b>"), "&lt;b&gt;Me&lt;/b&gt; (CC0)"),
    ],
)
def test_photo_credit(photo, credit):
    assert photo_credit(photo) == credit


def test_note_hash_is_stable_and_sensitive(observations, ancestries):
    obs = observations[125757925]
    a = note_for(obs, ancestries)
    assert note_hash(a) == note_hash(note_for(obs, ancestries))
    renamed = replace(obs, taxon=replace(obs.taxon, common_name="Red Campion"))
    assert note_hash(note_for(renamed, ancestries)) != note_hash(a)
    assert note_hash(render(obs, None, SOURCE)) != note_hash(a)  # tags count too


def test_anki_search():
    assert anki_search([456, 123]) == '"deck:iNaturalist::My observations" (ObsID:123 or ObsID:456)'
    assert anki_search([]) == ""
