"""Species and breed cards -> note fields and tags (SPEC-v2 5). Pure: no I/O."""

import hashlib
import json
from html import escape

from inat_anki.model import SPECIES_FIELD_NAMES, Card, CardNote
from inat_anki.render import _tag_part

TAXON_URL = "https://www.inaturalist.org/taxa/{id}"


def format_count(n: int | None) -> str:
    if not n:
        return ""
    return f"{n:,} UK observation{'' if n == 1 else 's'}"


def tags(card: Card) -> tuple[str, ...]:
    out = [f"inat::set::{card.set_key}"]
    if card.iconic:
        out.append(f"inat::iconic::{_tag_part(card.iconic)}")
    if card.order:
        out.append(f"inat::order::{_tag_part(card.order)}")
    if card.family:
        out.append(f"inat::family::{_tag_part(card.family)}")
    if card.breed_kind:
        out.append(f"breed::{card.breed_kind}")
    elif card.seen:  # breeds are never "seen": iNat does not record breeds
        out.append("inat::seen")
    return tuple(out)


def render_card(card: Card) -> CardNote:
    if not card.photos:
        raise ValueError(f"card {card.guid_parts} has no photos")
    front, *extra = card.photos
    values = {
        "TaxonID": str(card.sort_id),
        "FrontPhoto": f'<img src="{front.filename}">',
        "ExtraPhotos": "".join(f'<img src="{p.filename}">' for p in extra),
        "CommonName": escape(card.common_name or ""),
        "ScientificName": escape(card.scientific_name),
        "Rank": "" if card.rank == "species" else escape(card.rank),
        "Group": escape(card.set_name),
        "Family": escape(card.family or ""),
        "Order": escape(card.order or ""),
        "UKObservations": format_count(card.uk_count),
        "InfoURL": card.info_url,
        "PhotoCredits": "<br>".join(p.credit_html for p in card.photos),
        "Source": card.source,
    }
    return CardNote(
        guid_parts=card.guid_parts,
        set_key=card.set_key,
        fields=tuple(values[name] for name in SPECIES_FIELD_NAMES),
        tags=tags(card),
        front_media=front.filename,
        media=tuple(p.filename for p in card.photos),
    )


def card_hash(note: CardNote) -> str:
    """Same scheme as v1's note_hash: sha256 of the fields and tags as JSON."""
    payload = json.dumps({"fields": list(note.fields), "tags": list(note.tags)}, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def card_key(guid_parts: tuple) -> str:
    """A stable string key for state: e.g. "inat-place:6857:12748" or "breed:sheep/lleyn"."""
    return ":".join(str(p) for p in guid_parts)
