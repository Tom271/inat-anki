"""Rendered notes -> .apkg via genanki. Thin I/O layer.

The IDs and GUID scheme here are permanent: changing any of them makes Anki treat the
next import as a different note type, deck or note. See docs/anki-identity.md.
"""

import os
import tempfile
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

import genanki

from inat_anki.model import DECK_NAME, FIELD_NAMES, GUID_NAMESPACE_OBS, Note

# Generated once with random.randrange(1 << 30, 1 << 31). Never change them.
MODEL_ID = 1707931833
DECK_ID = 1527378531
MODEL_NAME = "iNaturalist observation"
CARD_NAME = "Photo"


def load_templates() -> tuple[str, str, str]:
    root = files("inat_anki") / "templates"
    return tuple((root / name).read_text() for name in ("front.html", "back.html", "style.css"))


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

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    os.close(fd)
    try:
        genanki.Package(deck, media_files=[str(p) for p in media.values()]).write_to_file(tmp)
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return missing
