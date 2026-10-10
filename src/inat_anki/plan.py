"""Diff fetched observations against state: what to download, what changed. Pure: no I/O."""

from collections.abc import Collection, Mapping

from inat_anki.model import Note, Observation, ObsRecord, PhotoDownload, PhotoRecord, Plan
from inat_anki.normalise import media_filename, photo_url
from inat_anki.render import note_hash

# Assumed sizes until the cache has real ones (SPEC 6).
DEFAULT_PHOTO_BYTES = {"large": 250_000, "medium": 80_000}


def estimate_photo_bytes(photos: Mapping[int, PhotoRecord], size: str) -> int:
    sizes = [p.bytes for p in photos.values() if p.size == size and p.bytes > 0]
    if not sizes:
        return DEFAULT_PHOTO_BYTES[size]
    return round(sum(sizes) / len(sizes))


def make_plan(
    observations: list[Observation],
    notes: Mapping[int, Note],
    known_obs: Mapping[int, ObsRecord],
    known_photos: Mapping[int, PhotoRecord],
    cached_ok: Collection[int],
    photo_size: str,
    refresh: bool = False,
    min_interval: float = 1.0,
) -> Plan:
    """Build the plan for one run.

    `notes` holds the rendered note for every observation that has photos.
    `cached_ok` holds the IDs of photos whose file exists and matches its sha256.
    """
    plan = Plan()
    fronts: list[PhotoDownload] = []
    extras: list[PhotoDownload] = []
    seen_photos: set[int] = set()

    for obs in observations:
        if not obs.photos:
            plan.skipped_no_photos.append(obs.id)
            continue
        record = known_obs.get(obs.id)
        if record is None:
            plan.new.append(obs.id)
        elif record.note_hash != note_hash(notes[obs.id]):
            plan.changed.append(obs.id)
        else:
            plan.unchanged.append(obs.id)

        for i, photo in enumerate(obs.photos):
            if photo.id in seen_photos:
                continue
            seen_photos.add(photo.id)
            cached = known_photos.get(photo.id)
            needed = (
                refresh or photo.id not in cached_ok or cached is None or cached.size != photo_size
            )
            if needed:
                download = PhotoDownload(
                    photo_id=photo.id,
                    obs_id=obs.id,
                    url=photo_url(photo, photo_size),
                    filename=media_filename(photo),
                    is_front=i == 0,
                )
                (fronts if i == 0 else extras).append(download)

    in_deck = set(plan.new) | set(plan.changed) | set(plan.unchanged)
    plan.removed = sorted(i for i in known_obs if i not in in_deck)
    plan.unreferenced_photos = sorted(i for i in known_photos if i not in seen_photos)
    # Front photos first: a run capped by --max-downloads then yields the most cards.
    plan.downloads = fronts + extras
    plan.estimated_bytes = len(plan.downloads) * estimate_photo_bytes(known_photos, photo_size)
    plan.estimated_seconds = len(plan.downloads) * min_interval
    return plan


def split_ready(
    notes: Mapping[int, Note], available_media: Collection[str]
) -> tuple[list[int], list[int]]:
    """Observation IDs whose front photo is available, and those deferred to a later run."""
    ready, deferred = [], []
    for obs_id, note in notes.items():
        (ready if note.front_media in available_media else deferred).append(obs_id)
    return sorted(ready), sorted(deferred)
