"""The photo cache: one file per photo, named inat_<photo_id>.<ext>. Thin I/O layer."""

import hashlib
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from inat_anki.api import ApiError, INatClient
from inat_anki.model import ChosenPhoto, Photo, PhotoDownload, PhotoRecord
from inat_anki.state import write_atomic

# Magic numbers of the image formats iNat serves.
IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")


class CorruptPhotoError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def looks_like_image(data: bytes) -> bool:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return any(data.startswith(sig) for sig in IMAGE_SIGNATURES)


def scan_cache(media_dir: Path, photos: Mapping[int, PhotoRecord]) -> set[int]:
    """IDs of cached photos whose file exists, has the recorded size and sha256."""
    ok = set()
    for photo_id, record in photos.items():
        path = media_dir / record.filename
        try:
            if path.stat().st_size != record.bytes:
                continue
            if sha256(path.read_bytes()) == record.sha256:
                ok.add(photo_id)
        except OSError:
            continue
    return ok


def fetch_image(client: INatClient, url: str, path: Path, expected_bytes: int) -> bytes:
    data = client.download(url, expected_bytes)
    if not looks_like_image(data):
        raise CorruptPhotoError(f"{url} did not return an image")
    write_atomic(path, data)
    return data


def download_photo(
    client: INatClient,
    download: PhotoDownload,
    photo: Photo,
    size: str,
    media_dir: Path,
    expected_bytes: int,
) -> PhotoRecord:
    data = fetch_image(client, download.url, media_dir / download.filename, expected_bytes)
    return PhotoRecord(
        filename=download.filename,
        size=size,
        bytes=len(data),
        license_code=photo.license_code,
        attribution=photo.attribution,
        sha256=sha256(data),
    )


def download_chosen(
    client: INatClient,
    photos: Iterable[ChosenPhoto],
    size: str,
    media_dir: Path,
    expected_bytes: int,
    on_saved: Callable[[ChosenPhoto, PhotoRecord], None],
    on_failed: Callable[[ChosenPhoto, Exception], None],
) -> None:
    """Like download_all, for photos chosen for species and breed cards."""
    for p in photos:
        try:
            data = fetch_image(client, p.url, media_dir / p.filename, expected_bytes)
        except CorruptPhotoError as e:
            on_failed(p, e)
            continue
        except ApiError as e:
            if e.status is None or e.status == 429 or e.status >= 500:
                raise
            on_failed(p, e)
            continue
        on_saved(
            p,
            PhotoRecord(
                filename=p.filename,
                size=size,
                bytes=len(data),
                license_code=p.license or None,
                attribution=p.credit_html,
                sha256=sha256(data),
            ),
        )


def download_all(
    client: INatClient,
    downloads: Iterable[PhotoDownload],
    photos: Mapping[int, Photo],
    size: str,
    media_dir: Path,
    expected_bytes: int,
    on_saved: Callable[[PhotoDownload, PhotoRecord], None],
    on_failed: Callable[[PhotoDownload, Exception], None],
) -> None:
    """Download photos one at a time. `on_saved` runs after each file is in place, so the
    caller can persist state and an interruption loses at most the photo in flight."""
    for d in downloads:
        try:
            record = download_photo(client, d, photos[d.photo_id], size, media_dir, expected_bytes)
        except CorruptPhotoError as e:
            on_failed(d, e)
            continue
        except ApiError as e:
            # A missing or forbidden photo skips just that photo. Throttling or server
            # trouble that outlasts every retry aborts the run, which can resume later.
            if e.status is None or e.status == 429 or e.status >= 500:
                raise
            on_failed(d, e)
            continue
        on_saved(d, record)


def prune(media_dir: Path, filenames: Iterable[str]) -> int:
    """Delete these cached files. Returns the number of bytes freed."""
    freed = 0
    for name in filenames:
        path = media_dir / name
        try:
            freed += path.stat().st_size
            path.unlink()
        except FileNotFoundError:
            continue
    return freed


def available_media(media_dir: Path, filenames: Iterable[str]) -> set[str]:
    return {name for name in filenames if (media_dir / name).is_file()}
