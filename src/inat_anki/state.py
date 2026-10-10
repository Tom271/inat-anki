"""state.json: what earlier runs cached and built. Schema in docs/state-schema.md."""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from inat_anki.model import ObsRecord, PhotoRecord, TaxonAncestry
from inat_anki.throttle import BandwidthWindow, DailyCounter

SCHEMA_VERSION = 1


class StateError(RuntimeError):
    pass


@dataclass
class State:
    source_key: str = ""
    photo_size: str = ""
    observations: dict[int, ObsRecord] = field(default_factory=dict)
    photos: dict[int, PhotoRecord] = field(default_factory=dict)
    taxa: dict[int, TaxonAncestry] = field(default_factory=dict)
    requests: DailyCounter = field(default_factory=DailyCounter)
    downloads: BandwidthWindow = field(default_factory=BandwidthWindow)


def to_json(state: State) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_key": state.source_key,
        "photo_size": state.photo_size,
        "observations": {
            str(i): {
                "updated_at": r.updated_at,
                "photo_ids": list(r.photo_ids),
                "note_hash": r.note_hash,
            }
            for i, r in sorted(state.observations.items())
        },
        "photos": {
            str(i): {
                "filename": r.filename,
                "size": r.size,
                "bytes": r.bytes,
                "license_code": r.license_code,
                "attribution": r.attribution,
                "sha256": r.sha256,
            }
            for i, r in sorted(state.photos.items())
        },
        "taxa": {
            str(i): {"order": t.order, "family": t.family} for i, t in sorted(state.taxa.items())
        },
        "requests": {"day": state.requests.day, "count": state.requests.count},
        "downloads": [[t, b] for t, b in state.downloads.entries],
    }


def from_json(d: dict) -> State:
    version = d.get("schema_version")
    if version != SCHEMA_VERSION:
        raise StateError(
            f"state schema_version {version!r} is not supported (expected {SCHEMA_VERSION})"
        )
    return State(
        source_key=d.get("source_key", ""),
        photo_size=d.get("photo_size", ""),
        observations={
            int(i): ObsRecord(r["updated_at"], tuple(r["photo_ids"]), r["note_hash"])
            for i, r in d.get("observations", {}).items()
        },
        photos={
            int(i): PhotoRecord(
                r["filename"],
                r["size"],
                r["bytes"],
                r["license_code"],
                r["attribution"],
                r["sha256"],
            )
            for i, r in d.get("photos", {}).items()
        },
        taxa={
            int(i): TaxonAncestry(int(i), t["order"], t["family"])
            for i, t in d.get("taxa", {}).items()
        },
        requests=DailyCounter(
            day=d.get("requests", {}).get("day", ""), count=d.get("requests", {}).get("count", 0)
        ),
        downloads=BandwidthWindow(entries=[(t, b) for t, b in d.get("downloads", [])]),
    )


def write_atomic(path: Path, data: bytes) -> None:
    """Write to a temporary file in the same directory, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load(path: Path) -> State:
    if not path.exists():
        return State()
    try:
        return from_json(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise StateError(f"{path} is not a valid state file: {e}") from e


def save(state: State, path: Path) -> None:
    write_atomic(path, (json.dumps(to_json(state), indent=1) + "\n").encode())
