import json
import re
import sqlite3
import tomllib
import zipfile
from pathlib import Path

import genanki
import pytest

from inat_anki import deck
from inat_anki.model import SPECIES_FIELD_NAMES, Card, ChosenPhoto
from inat_anki.render_species import render_card
from inat_anki.sets import parse_sets

ROOT = Path(__file__).parent.parent
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


def photo(name):
    return ChosenPhoto(f"k:{name}", name, "u", f"credit {name}", "s")


def card(set_key, tid, *media, **kw):
    base = dict(
        guid_parts=("inat-place", "6857", tid),
        set_key=set_key,
        set_name=set_key,
        sort_id=tid,
        common_name=f"Species {tid}",
        scientific_name=f"Genus {tid}",
        rank="species",
        family="F",
        order="O",
        iconic="Aves",
        uk_count=10,
        info_url="https://www.inaturalist.org/taxa/1",
        source=f"place:6857:{set_key}",
        photos=tuple(photo(m) for m in media),
    )
    return render_card(Card(**{**base, **kw}))


@pytest.fixture
def media_dir(tmp_path):
    d = tmp_path / "media"
    d.mkdir()
    for name in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):
        (d / name).write_bytes(JPEG)
    return d


def open_apkg(path, tmp_path):
    with zipfile.ZipFile(path) as z:
        z.extractall(tmp_path / "x")
    return sqlite3.connect(tmp_path / "x" / "collection.anki2")


def test_species_ids_are_constant_and_distinct():
    assert deck.SPECIES_MODEL_ID == 1713941905
    assert deck.SPECIES_MODEL_ID != deck.MODEL_ID
    assert (1 << 30) <= deck.SPECIES_MODEL_ID < (1 << 31)


def test_deck_ids_derived_and_pinned():
    assert deck.deck_id_for("birds") == deck.deck_id_for("birds")
    assert deck.deck_id_for("birds") != deck.deck_id_for("mammals")
    # Pinned so the web app can be checked against it.
    assert deck.deck_id_for("birds") == 2113160693
    config = parse_sets(tomllib.loads((ROOT / "sets/uk-common.toml").read_text()))
    ids = [deck.deck_id_for(s.key) for s in config.sets]
    assert len(set(ids)) == len(ids)
    assert all((1 << 30) <= i < (1 << 31) for i in ids)
    assert deck.DECK_ID not in ids


def test_species_model_fields():
    model = deck.build_species_model()
    assert [f["name"] for f in model.fields] == list(SPECIES_FIELD_NAMES)
    assert model.sort_field_index == 0
    front, back, css = deck.load_templates("species")
    used = set(re.findall(r"{{[#^/]?(\w+)}}", front + back)) - {"FrontSide", "Tags"}
    assert used <= set(SPECIES_FIELD_NAMES)
    assert ".nightMode" in css and ".seen-badge" in css


def test_package_has_one_deck_per_set(media_dir, tmp_path):
    decks = [
        (
            "birds",
            "iNaturalist::UK common species::Birds",
            [card("birds", 1, "a.jpg", "b.jpg"), card("birds", 2, "c.jpg")],
        ),
        (
            "farm-breeds",
            "iNaturalist::UK common species::Farm breeds",
            [
                card(
                    "farm-breeds",
                    74113,
                    "d.jpg",
                    guid_parts=("breed", "cattle/hereford"),
                    rank="breed",
                    breed_kind="cattle",
                )
            ],
        ),
    ]
    out = tmp_path / "species.apkg"
    assert deck.build_species_package(decks, "About these photos", media_dir, out) == []
    db = open_apkg(out, tmp_path)
    all_decks = json.loads(db.execute("select decks from col").fetchone()[0])
    names = {d["name"]: d for d in all_decks.values()}
    assert "iNaturalist::UK common species::Birds" in names
    assert names["iNaturalist::UK common species::Farm breeds"]["desc"] == "About these photos"
    rows = db.execute("select guid, mid, tags from notes").fetchall()
    assert len(rows) == 3 and {r[1] for r in rows} == {deck.SPECIES_MODEL_ID}
    assert genanki.guid_for("breed", "cattle/hereford") in {r[0] for r in rows}
    cards = db.execute("select did from cards").fetchall()
    assert {c[0] for c in cards} == {deck.deck_id_for("birds"), deck.deck_id_for("farm-breeds")}


def test_duplicate_note_rejected(media_dir, tmp_path):
    decks = [("a", "A", [card("a", 1, "a.jpg")]), ("b", "B", [card("b", 1, "b.jpg")])]
    with pytest.raises(ValueError, match="duplicate"):
        deck.build_species_package(decks, "", media_dir, tmp_path / "x.apkg")


def test_missing_front_and_extra(media_dir, tmp_path):
    with pytest.raises(FileNotFoundError):
        deck.build_species_package(
            [("a", "A", [card("a", 1, "zz.jpg")])], "", media_dir, tmp_path / "x.apkg"
        )
    missing = deck.build_species_package(
        [("a", "A", [card("a", 1, "a.jpg", "zz.jpg")])], "", media_dir, tmp_path / "y.apkg"
    )
    assert missing == ["zz.jpg"]
