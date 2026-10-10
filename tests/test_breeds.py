import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from inat_anki.breeds import (
    BreedsError,
    candidates,
    choose_breed_photos,
    commons_credit,
    commons_file_from_api,
    commons_filename,
    commons_license_ok,
    parse_breeds,
    strip_html,
    wikipedia_url,
)
from tests.conftest import load_fixture

ROOT = Path(__file__).parent.parent


@pytest.fixture
def files():
    pages = load_fixture("v2_commons_category.json")["query"]["pages"]
    return [f for f in (commons_file_from_api(p) for p in pages) if f]


@pytest.fixture
def breeds():
    return parse_breeds(tomllib.loads((ROOT / "lists/uk-farm-breeds.toml").read_text()))


def test_shipped_breed_list(breeds):
    kinds = [b.key.split("/")[0] for b in breeds]
    assert (kinds.count("cattle"), kinds.count("sheep"), kinds.count("pig")) == (10, 10, 5)
    assert breeds[9].name == "Highland"
    assert breeds[-1].name == "Berkshire"


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("cc0", True),
        ("pd", True),
        ("cc-by-2.0", True),
        ("cc-by-4.0", True),
        ("cc-by-sa-2.0", True),
        ("cc-by-sa-3.0-de", True),
        ("cc-by-sa-4.0", True),
        ("CC-BY-SA-4.0", True),
        ("cc-by-2.5", True),
        ("", False),
        ("gfdl", False),
        ("cc-sa-1.0", False),
        ("cc-by-nc-2.0", False),
        ("cc-by-nd-4.0", False),
        ("fal", False),
        ("cc-by-sa", False),
        ("attribution", False),
    ],
)
def test_commons_licence_mapping(value, ok):
    assert commons_license_ok(value) is ok


def test_commons_file_parsed(files):
    f = files[0]
    assert f.title.startswith("File:")
    assert f.license == "cc-by-sa-3.0"
    assert f.license_short == "CC BY-SA 3.0"
    assert f.artist == "Photographer 0"  # HTML stripped
    assert f.page_url.startswith("https://commons.wikimedia.org/wiki/File:")
    assert f.thumb_url


def test_empty_metadata_list_is_handled():
    f = commons_file_from_api(
        {
            "title": "File:X.jpg",
            "imageinfo": [
                {"url": "u", "mime": "image/jpeg", "width": 2000, "height": 1000, "extmetadata": []}
            ],
        }
    )
    assert f.license == ""
    assert not candidates([f])


def test_candidates_filter_pdf_small_and_unlicensed(files):
    titles = [f.title for f in candidates(files)]
    assert not any(t.endswith(".pdf") for t in titles)
    assert "File:El Bóalo 1975.jpg" not in titles  # 996 px
    assert len(titles) == 10


def test_restrictions_reject(files):
    restricted = replace(files[0], restrictions="personality")
    assert candidates([restricted]) == []


def test_candidates_deduplicated(files):
    assert len(candidates(files + files)) == len(candidates(files))


def test_pinned_photos_first(breeds, files):
    cands = candidates(files)
    breed = replace(breeds[6], photos=(cands[3].title, cands[5].title))
    chosen, reviewed, problems = choose_breed_photos(breed, {f.title: f for f in files}, cands, 2)
    assert [c.source_id for c in chosen] == [cands[3].title, cands[5].title]
    assert reviewed and problems == []


def test_unpinned_uses_candidates_and_is_unreviewed(breeds, files):
    cands = candidates(files)
    chosen, reviewed, _ = choose_breed_photos(breeds[6], {}, cands, 2)
    assert [c.source_id for c in chosen] == [cands[0].title, cands[1].title]
    assert not reviewed


def test_deleted_or_relicensed_pin_reported(breeds, files):
    cands = candidates(files)
    gone = "File:Deleted.jpg"
    bad = replace(cands[2], license="cc-by-nc-2.0")
    breed = replace(breeds[6], photos=(gone, bad.title))
    chosen, reviewed, problems = choose_breed_photos(breed, {bad.title: bad}, cands, 2)
    assert len(problems) == 2
    assert not reviewed
    assert len(chosen) == 2 and bad.title not in [c.source_id for c in chosen]


def test_one_or_no_candidates(breeds, files):
    one = candidates(files)[:1]
    assert len(choose_breed_photos(breeds[6], {}, one, 2)[0]) == 1
    assert choose_breed_photos(breeds[6], {}, [], 2)[0] == []


def test_credit_and_filename(files):
    f = candidates(files)[0]
    credit = commons_credit(f)
    assert f.license_url in credit and "Wikimedia Commons" in credit
    pd = next(x for x in files if x.license == "pd" and x.mime == "image/jpeg")
    assert "Public domain" in commons_credit(pd)
    assert commons_filename(f.title) == commons_filename(f.title)
    assert commons_filename(f.title).startswith("commons_") and commons_filename(f.title).endswith(
        ".jpg"
    )


def test_strip_html():
    assert strip_html('<a href="x">Jo &amp; Al</a> <span>(talk)</span>') == "Jo & Al (talk)"


def test_wikipedia_url(breeds):
    assert wikipedia_url(breeds[0]) == "https://en.wikipedia.org/wiki/Holstein_Friesian"


@pytest.mark.parametrize(
    "breed",
    [
        {
            "key": "goat/x",
            "name": "x",
            "species": "s",
            "taxon_id": 1,
            "commons_category": "c",
            "wikipedia": "w",
        },
        {"key": "sheep/x", "name": "x"},
        {
            "key": "sheep/x",
            "name": "x",
            "species": "s",
            "taxon_id": 1,
            "commons_category": "c",
            "wikipedia": "w",
            "colour": "red",
        },
    ],
)
def test_bad_breed_rejected(breed):
    with pytest.raises(BreedsError):
        parse_breeds({"breed": [breed]})
