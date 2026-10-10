"""Rendered notes -> .apkg via genanki. Thin I/O layer.

The IDs and GUID scheme here are permanent: changing any of them makes Anki treat the
next import as a different note type, deck or note. See docs/anki-identity.md.
"""

import hashlib
import os
import tempfile
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

import genanki

from inat_anki.model import (
    DECK_NAME,
    FIELD_NAMES,
    GUID_NAMESPACE_OBS,
    SPECIES_FIELD_NAMES,
    CardNote,
    Note,
)

# Generated once with random.randrange(1 << 30, 1 << 31). Never change them.
MODEL_ID = 1707931833
DECK_ID = 1527378531
MODEL_NAME = "iNaturalist observation"
CARD_NAME = "Photo"


# v2 species and breed cards (SPEC-v2 5). Generated once; never change.
SPECIES_MODEL_ID = 1713941905
SPECIES_MODEL_NAME = "iNaturalist species"
DECK_ID_SALT = "inat-anki-deck:"


def load_templates(kind: str = "") -> tuple[str, str, str]:
    root = files("inat_anki") / "templates"
    sub = root / kind if kind else root
    front, back = ((sub / name).read_text() for name in ("front.html", "back.html"))
    css = (root / "style.css").read_text()
    if kind:
        css += "\n" + (sub / "style.css").read_text()
    return front, back, css


def build_model() -> genanki.Model:
    front, back, css = load_templates()
    return genanki.Model(
        MODEL_ID,
        MODEL_NAME,
        fields=[{"name": name} for name in FIELD_NAMES],
        templates=[{"name": CARD_NAME, "qfmt": front, "afmt": back}],
        css=css,
        sort_field_index=FIELD_NAMES.index("ObsID"),
    )


def note_guid(obs_id: int) -> str:
    return genanki.guid_for(GUID_NAMESPACE_OBS, obs_id)


def build_species_model() -> genanki.Model:
    front, back, css = load_templates("species")
    return genanki.Model(
        SPECIES_MODEL_ID,
        SPECIES_MODEL_NAME,
        fields=[{"name": name} for name in SPECIES_FIELD_NAMES],
        templates=[{"name": CARD_NAME, "qfmt": front, "afmt": back}],
        css=css,
        sort_field_index=SPECIES_FIELD_NAMES.index("TaxonID"),
    )


def deck_id_for(set_key: str) -> int:
    """Stable deck ID for a config-defined set: first 8 bytes of sha256, mapped into
    [1 << 30, 1 << 31) as genanki recommends (SPEC-v2 5.1)."""
    digest = hashlib.sha256((DECK_ID_SALT + set_key).encode()).digest()
    return (1 << 30) + int.from_bytes(digest[:8], "big") % (1 << 30)


def build_package(notes: Iterable[Note], media_dir: Path, out: Path) -> list[str]:
    """Write an .apkg with these notes and the media they reference.

    Each note's front photo must exist in `media_dir` (defer notes without one). Missing
    extra photos are left out and returned, so the caller can rebuild those notes later.
    """
    model = build_model()
    deck = genanki.Deck(DECK_ID, DECK_NAME)
    media: dict[str, Path] = {}
    missing: list[str] = []
    for note in sorted(notes, key=lambda n: n.obs_id):
        deck.add_note(
            genanki.Note(
                model=model,
                fields=list(note.fields),
                tags=list(note.tags),
                guid=note_guid(note.obs_id),
            )
        )
        for name in note.media:
            path = media_dir / name
            if path.is_file():
                media[name] = path
            elif name == note.front_media:
                raise FileNotFoundError(f"front photo {path} is missing")
            else:
                missing.append(name)

    _write_package([deck], media, out)
    return missing


def _write_package(decks: list[genanki.Deck], media: dict[str, Path], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    os.close(fd)
    try:
        genanki.Package(decks, media_files=[str(p) for p in media.values()]).write_to_file(tmp)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; this is a normal user file
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def build_species_package(
    decks: list[tuple[str, str, list[CardNote]]],
    description: str,
    media_dir: Path,
    out: Path,
) -> list[str]:
    """Write one .apkg with a subdeck per set: `decks` holds (set key, deck name, notes).

    As build_package: front photos must exist; missing extra photos are returned.
    """
    model = build_species_model()
    built, media, missing, guids = [], {}, [], set()
    for set_key, name, notes in decks:
        deck = genanki.Deck(deck_id_for(set_key), name, description=description)
        for note in notes:
            guid = genanki.guid_for(*note.guid_parts)
            if guid in guids:
                raise ValueError(f"duplicate note {note.guid_parts}")
            guids.add(guid)
            deck.add_note(
                genanki.Note(model=model, fields=list(note.fields), tags=list(note.tags), guid=guid)
            )
            for m in note.media:
                path = media_dir / m
                if path.is_file():
                    media[m] = path
                elif m == note.front_media:
                    raise FileNotFoundError(f"front photo {path} is missing")
                else:
                    missing.append(m)
        built.append(deck)
    _write_package(built, media, out)
    return missing
