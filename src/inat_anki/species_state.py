"""State for the species decks: <cache-dir>/state.json (docs/state-schema-species.md)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from inat_anki.model import PhotoRecord
from inat_anki.state import StateError, write_atomic
from inat_anki.throttle import BandwidthWindow, DailyCounter

SCHEMA_VERSION = 1
KIND = "species"


@dataclass
class TaxonInfo:
    name: str
    rank: str
    common_name: str | None
    iconic: str | None
    order: str | None
    family: str | None


@dataclass
class Choice:
    key: str  # ChosenPhoto key: "inat:<id>" or "commons:<title>"
    source_id: str  # observation ID or Commons title


@dataclass
class SpeciesState:
    source_key: str = ""
    photo_size: str = ""
    members: dict[str, list] = field(default_factory=dict)  # set key -> taxon IDs/breed keys
    counts: dict[int, int] = field(default_factory=dict)  # taxon ID -> last UK count
    taxa: dict[int, TaxonInfo] = field(default_factory=dict)
    choices: dict[str, list[Choice]] = field(default_factory=dict)  # card key -> photos
    notes: dict[str, str] = field(default_factory=dict)  # card key -> card hash ("" = rebuild)
    photos: dict[str, PhotoRecord] = field(default_factory=dict)  # photo key -> file
    requests: DailyCounter = field(default_factory=DailyCounter)
    downloads: BandwidthWindow = field(default_factory=BandwidthWindow)


def to_json(st: SpeciesState) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "source_key": st.source_key,
        "photo_size": st.photo_size,
        "members": st.members,
        "counts": {str(k): v for k, v in sorted(st.counts.items())},
        "taxa": {str(k): vars(v) for k, v in sorted(st.taxa.items())},
        "choices": {k: [vars(c) for c in v] for k, v in sorted(st.choices.items())},
        "notes": dict(sorted(st.notes.items())),
        "photos": {k: vars(v) for k, v in sorted(st.photos.items())},
        "requests": {"day": st.requests.day, "count": st.requests.count},
        "downloads": [[t, b] for t, b in st.downloads.entries],
    }


def from_json(d: dict) -> SpeciesState:
    if d.get("schema_version") != SCHEMA_VERSION or d.get("kind") != KIND:
        raise StateError(
            f"not a species state file (schema_version {d.get('schema_version')!r}, "
            f"kind {d.get('kind')!r}); use a separate --cache-dir from the v1 sync"
        )
    req = d.get("requests", {})
    return SpeciesState(
        source_key=d.get("source_key", ""),
        photo_size=d.get("photo_size", ""),
        members={k: list(v) for k, v in d.get("members", {}).items()},
        counts={int(k): v for k, v in d.get("counts", {}).items()},
        taxa={int(k): TaxonInfo(**v) for k, v in d.get("taxa", {}).items()},
        choices={k: [Choice(**c) for c in v] for k, v in d.get("choices", {}).items()},
        notes=dict(d.get("notes", {})),
        photos={k: PhotoRecord(**v) for k, v in d.get("photos", {}).items()},
        requests=DailyCounter(day=req.get("day", ""), count=req.get("count", 0)),
        downloads=BandwidthWindow(entries=[(t, b) for t, b in d.get("downloads", [])]),
    )


def load(path: Path) -> SpeciesState:
    if not path.exists():
        return SpeciesState()
    try:
        return from_json(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise StateError(f"{path} is not a valid species state file: {e}") from e


def save(st: SpeciesState, path: Path) -> None:
    write_atomic(path, (json.dumps(to_json(st), indent=1, ensure_ascii=False) + "\n").encode())
