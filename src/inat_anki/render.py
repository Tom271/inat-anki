"""Observation -> Anki note fields and tags. Pure: no I/O."""

import hashlib
import json
from datetime import date, datetime
from html import escape

from inat_anki.licensing import license_label
from inat_anki.model import DECK_NAME, FIELD_NAMES, Note, Observation, Photo, TaxonAncestry
from inat_anki.normalise import media_filename

# Spelled out rather than using strftime, so the output does not depend on the system
# locale and the TypeScript port can copy the tables.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

OBS_URL = "https://www.inaturalist.org/observations/{id}"


def format_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def format_observed(obs: Observation) -> str:
    """British format in the observation's local time, e.g. "Sat 4 May 2024, 14:32"."""
    if obs.time_observed_at:
        # The offset in time_observed_at is the one in effect locally, so the wall time
        # is already local. Never use the API's time_zone_offset (it ignores DST).
        dt = datetime.fromisoformat(obs.time_observed_at)
        return f"{format_date(dt.date())}, {dt:%H:%M}"
    if obs.observed_on:
        return format_date(date.fromisoformat(obs.observed_on))
    return ""


def format_place(obs: Observation) -> str:
    place = escape(obs.place_guess or "")
    if obs.obscured:
        return f"{place} (location obscured)".strip()
    return place


def format_coordinates(obs: Observation) -> str:
    if obs.obscured or obs.latitude is None or obs.longitude is None:
        return ""
    text = f"{obs.latitude:.5f}, {obs.longitude:.5f}"
    if obs.accuracy_m is not None:
        text += f" (±{obs.accuracy_m} m)"
    return text


def img_tag(photo: Photo) -> str:
    return f'<img src="{media_filename(photo)}">'


def photo_credit(photo: Photo) -> str:
    """iNat's attribution already names the licence ("..., some rights reserved (CC BY)",
    "..., all rights reserved"), so the label is added only when it is missing."""
    label = license_label(photo.license_code)
    attribution = photo.attribution.strip()
    if not attribution:
        return escape(label)
    if label.lower() in attribution.lower():
        return escape(attribution)
    return escape(f"{attribution} ({label})")


def _tag_part(value: str) -> str:
    # Anki tags cannot contain spaces.
    return "_".join(value.split())


def tags(obs: Observation, ancestry: TaxonAncestry | None) -> tuple[str, ...]:
    out = []
    if obs.taxon.iconic_taxon_name:
        out.append(f"inat::iconic::{_tag_part(obs.taxon.iconic_taxon_name)}")
    if ancestry and ancestry.order:
        out.append(f"inat::order::{_tag_part(ancestry.order)}")
    if ancestry and ancestry.family:
        out.append(f"inat::family::{_tag_part(ancestry.family)}")
    out.append(f"inat::user::{_tag_part(obs.user_login)}")
    return tuple(out)


def render(obs: Observation, ancestry: TaxonAncestry | None, source_key: str) -> Note:
    """Render an observation that has at least one photo."""
    if not obs.photos:
        raise ValueError(f"observation {obs.id} has no photos")
    front, *extra = obs.photos
    values = {
        "ObsID": str(obs.id),
        "FrontPhoto": img_tag(front),
        "ExtraPhotos": "".join(img_tag(p) for p in extra),
        "CommonName": escape(obs.taxon.common_name or ""),
        "ScientificName": escape(obs.taxon.name),
        "Rank": "" if obs.taxon.rank == "species" else escape(obs.taxon.rank),
        "ObservedOn": format_observed(obs),
        "Place": format_place(obs),
        "Coordinates": format_coordinates(obs),
        "ObsURL": OBS_URL.format(id=obs.id),
        "TaxonID": str(obs.taxon.id),
        "Source": source_key,
        "PhotoCredits": "<br>".join(photo_credit(p) for p in obs.photos),
    }
    return Note(
        obs_id=obs.id,
        fields=tuple(values[name] for name in FIELD_NAMES),
        tags=tags(obs, ancestry),
        front_media=media_filename(front),
        media=tuple(media_filename(p) for p in obs.photos),
    )


def note_hash(note: Note) -> str:
    """Hash of everything Anki would store for the note: fields and tags."""
    payload = json.dumps({"fields": list(note.fields), "tags": list(note.tags)}, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def anki_search(obs_ids: list[int], deck_name: str = DECK_NAME) -> str:
    """A search to paste into Anki's browser to find notes for these observations."""
    if not obs_ids:
        return ""
    terms = " or ".join(f"ObsID:{i}" for i in sorted(obs_ids))
    return f'"deck:{deck_name}" ({terms})'
