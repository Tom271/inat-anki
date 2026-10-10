import pytest

from inat_anki.model import SPECIES_FIELD_NAMES, Card, ChosenPhoto
from inat_anki.render_species import card_hash, card_key, format_count, render_card


def photo(i):
    return ChosenPhoto(f"inat:{i}", f"inat_{i}.jpg", "u", f"credit {i}", str(i))


def card(**kw):
    base = dict(
        guid_parts=("inat-place", "6857", 12748),
        set_key="birds",
        set_name="Birds",
        sort_id=12748,
        common_name="European Robin",
        scientific_name="Erithacus rubecula",
        rank="species",
        family="Muscicapidae",
        order="Passeriformes",
        iconic="Aves",
        uk_count=43195,
        info_url="https://www.inaturalist.org/taxa/12748",
        source="place:6857:birds",
        photos=(photo(1), photo(2)),
    )
    return Card(**{**base, **kw})


def test_fields_in_order():
    note = render_card(card())
    assert len(note.fields) == len(SPECIES_FIELD_NAMES)
    assert note.field("FrontPhoto") == '<img src="inat_1.jpg">'
    assert note.field("ExtraPhotos") == '<img src="inat_2.jpg">'
    assert note.field("UKObservations") == "43,195 UK observations"
    assert note.field("Rank") == ""
    assert note.field("PhotoCredits") == "credit 1<br>credit 2"
    assert note.media == ("inat_1.jpg", "inat_2.jpg")


def test_tags_and_seen():
    assert render_card(card()).tags == (
        "inat::set::birds",
        "inat::iconic::Aves",
        "inat::order::Passeriformes",
        "inat::family::Muscicapidae",
    )
    assert "inat::seen" in render_card(card(seen=True)).tags


def test_breed_card_never_seen():
    note = render_card(
        card(
            seen=True,
            breed_kind="sheep",
            rank="breed",
            uk_count=None,
            guid_parts=("breed", "sheep/lleyn"),
        )
    )
    assert "breed::sheep" in note.tags and "inat::seen" not in note.tags
    assert note.field("Rank") == "breed"
    assert note.field("UKObservations") == ""


def test_escaping():
    note = render_card(card(common_name="Fish & <Chips>"))
    assert note.field("CommonName") == "Fish &amp; &lt;Chips&gt;"


def test_hash_changes_with_seen():
    assert card_hash(render_card(card())) != card_hash(render_card(card(seen=True)))
    assert card_hash(render_card(card())) == card_hash(render_card(card()))


def test_no_photos_rejected():
    with pytest.raises(ValueError):
        render_card(card(photos=()))


def test_keys_and_counts():
    assert card_key(("inat-place", "6857", 12748)) == "inat-place:6857:12748"
    assert card_key(("breed", "sheep/lleyn")) == "breed:sheep/lleyn"
    assert format_count(None) == "" and format_count(1) == "1 UK observation"
