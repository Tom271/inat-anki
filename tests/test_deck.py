import json
import re
import sqlite3
import zipfile

import pytest

from inat_anki import deck
from inat_anki.model import FIELD_NAMES
from inat_anki.render import render

SOURCE = "user:example_user"
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


@pytest.fixture
def notes(observations, ancestries):
    return [render(o, ancestries.get(o.taxon.id), SOURCE) for o in observations.values()]


@pytest.fixture
def media_dir(tmp_path, notes):
    d = tmp_path / "media"
    d.mkdir()
    for n in notes:
        for name in n.media:
            (d / name).write_bytes(JPEG)
    return d


def open_apkg(path, tmp_path):
    with zipfile.ZipFile(path) as z:
        z.extractall(tmp_path / "unzipped")
        names = z.namelist()
    root = tmp_path / "unzipped"
    db = sqlite3.connect(root / "collection.anki2")
    media_map = json.loads((root / "media").read_text())
    return db, media_map, names


def test_ids_are_constant():
    # These must never change: Anki would see a new note type and a new deck.
    assert deck.MODEL_ID == 1707931833
    assert deck.DECK_ID == 1527378531
    assert (1 << 30) <= deck.MODEL_ID < (1 << 31)
    assert (1 << 30) <= deck.DECK_ID < (1 << 31)


def test_guid_scheme_is_stable():
    assert deck.note_guid(125757925) == deck.note_guid(125757925)
    assert deck.note_guid(125757925) != deck.note_guid(125757926)
    # genanki.guid_for("inat-obs", 125757925): sha256("inat-obs__125757925"), base91.
    # Pinned so the TypeScript port can be checked against it.
    assert deck.note_guid(125757925) == "e#pdPz/Wlu"


def test_model_fields_in_order():
    model = deck.build_model()
    assert [f["name"] for f in model.fields] == list(FIELD_NAMES)
    assert model.sort_field_index == 0


def test_apkg_opens_and_contains_notes(notes, media_dir, tmp_path):
    out = tmp_path / "out.apkg"
    assert deck.build_package(notes, media_dir, out) == []
    db, media_map, _ = open_apkg(out, tmp_path)
    rows = db.execute("select guid, mid, flds, tags, sfld from notes order by sfld").fetchall()
    assert len(rows) == len(notes)
    by_id = {n.obs_id: n for n in notes}
    for guid, mid, flds, tags, sfld in rows:
        note = by_id[int(sfld)]
        assert mid == deck.MODEL_ID
        assert guid == deck.note_guid(note.obs_id)
        assert flds.split("\x1f") == list(note.fields)
        assert tags.split() == list(note.tags)
    decks = json.loads(db.execute("select decks from col").fetchone()[0])
    assert decks[str(deck.DECK_ID)]["name"] == "iNaturalist::My observations"
    assert sorted(media_map.values()) == sorted({m for n in notes for m in n.media})


def test_guids_stable_across_builds(notes, media_dir, tmp_path):
    guids = []
    for i in range(2):
        out = tmp_path / f"build{i}.apkg"
        deck.build_package(notes, media_dir, out)
        db, _, _ = open_apkg(out, tmp_path / f"x{i}")
        guids.append(sorted(r[0] for r in db.execute("select guid from notes")))
    assert guids[0] == guids[1]


def test_media_filenames_unique(notes):
    names = [m for n in notes for m in n.media]
    assert len(names) == len(set(names))


def test_missing_front_photo_raises(notes, media_dir, tmp_path):
    (media_dir / notes[0].front_media).unlink()
    with pytest.raises(FileNotFoundError):
        deck.build_package(notes, media_dir, tmp_path / "out.apkg")
    assert not (tmp_path / "out.apkg").exists()


def test_missing_extra_photo_is_reported(notes, media_dir, tmp_path):
    multi = next(n for n in notes if len(n.media) > 1)
    (media_dir / multi.media[1]).unlink()
    out = tmp_path / "out.apkg"
    assert deck.build_package(notes, media_dir, out) == [multi.media[1]]
    _, media_map, _ = open_apkg(out, tmp_path)
    assert multi.media[1] not in media_map.values()


def test_templates_reference_only_real_fields():
    front, back, _ = deck.load_templates()
    used = set(re.findall(r"{{[#^/]?(\w+)}}", front + back)) - {"FrontSide"}
    assert used <= set(FIELD_NAMES)
