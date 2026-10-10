"""Farm breeds: the breeds list, Commons licences and breed photos (SPEC-v2 4.3, 6.2).

Pure: no I/O.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping
from html import escape, unescape

from inat_anki.model import Breed, ChosenPhoto, CommonsFile

BREED_KEYS = {
    "key",
    "name",
    "species",
    "taxon_id",
    "commons_category",
    "wikipedia",
    "photos",
    "search",
}
OPTIONAL_KEYS = {"photos", "search"}
BREED_KEY_RE = re.compile(r"^(cattle|sheep|pig)/[a-z0-9-]+$")
MIN_LONG_SIDE = 1024
COMMONS_FILE_URL = "https://commons.wikimedia.org/wiki/{title}"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/{title}"

# Shareable Commons licences: CC0, public domain, CC BY and CC BY-SA in any version, with
# or without a jurisdiction port (e.g. cc-by-sa-3.0-de). Everything else is rejected.
SHAREABLE_COMMONS = re.compile(r"^(cc0|pd|cc-by(-sa)?-\d(\.\d)?(-[a-z]{2,})?)$")


class BreedsError(ValueError):
    pass


def parse_breeds(raw: dict) -> list[Breed]:
    out = []
    for i, b in enumerate(raw.get("breed") or []):
        where = f"breed {b.get('key', i + 1)}"
        bad = set(b) - BREED_KEYS
        if bad:
            raise BreedsError(f"{where}: unknown field(s): {', '.join(sorted(bad))}")
        missing = BREED_KEYS - OPTIONAL_KEYS - set(b)
        if missing:
            raise BreedsError(f"{where}: missing field(s): {', '.join(sorted(missing))}")
        if not BREED_KEY_RE.match(b["key"]):
            raise BreedsError(f"{where}: key must look like cattle/<name>, sheep/... or pig/...")
        out.append(
            Breed(
                key=b["key"],
                name=b["name"],
                species=b["species"],
                taxon_id=int(b["taxon_id"]),
                commons_category=b["commons_category"],
                wikipedia=b["wikipedia"],
                photos=tuple(b.get("photos") or ()),
                search=b.get("search", ""),
            )
        )
    keys = [b.key for b in out]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise BreedsError(f"duplicate breed key(s): {', '.join(dupes)}")
    return out


def breed_kind(breed: Breed) -> str:
    return breed.key.split("/", 1)[0]


def search_phrase(breed: Breed) -> str:
    return breed.search or f"{breed.name} {breed_kind(breed)}"


def wikipedia_url(breed: Breed) -> str:
    return WIKIPEDIA_URL.format(title=breed.wikipedia.replace(" ", "_"))


def strip_html(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def commons_file_from_api(page: dict) -> CommonsFile | None:
    """One page of a MediaWiki query with prop=imageinfo&iiprop=url|mime|size|extmetadata."""
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    md = info.get("extmetadata")
    md = md if isinstance(md, dict) else {}  # empty metadata comes back as a list

    def meta(key: str) -> str:
        return str((md.get(key) or {}).get("value") or "")

    title = page["title"]
    return CommonsFile(
        title=title,
        thumb_url=info.get("thumburl") or info.get("url") or "",
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        mime=info.get("mime") or "",
        license=meta("License").lower(),
        license_short=strip_html(meta("LicenseShortName")),
        license_url=meta("LicenseUrl"),
        artist=strip_html(meta("Artist")),
        attribution=strip_html(meta("Attribution")),
        restrictions=meta("Restrictions"),
        page_url=COMMONS_FILE_URL.format(title=title.replace(" ", "_")),
    )


def commons_license_ok(value: str) -> bool:
    return bool(SHAREABLE_COMMONS.match((value or "").lower()))


def is_candidate(f: CommonsFile) -> bool:
    return (
        f.mime == "image/jpeg"
        and max(f.width, f.height) >= MIN_LONG_SIDE
        and commons_license_ok(f.license)
        and not f.restrictions
        and bool(f.thumb_url)
    )


def candidates(files: Iterable[CommonsFile]) -> list[CommonsFile]:
    """Usable files in order, without duplicates (category and search results overlap)."""
    out, seen = [], set()
    for f in files:
        if f.title not in seen and is_candidate(f):
            seen.add(f.title)
            out.append(f)
    return out


def commons_filename(title: str) -> str:
    return f"commons_{hashlib.sha256(title.encode()).hexdigest()[:16]}.jpg"


def commons_credit(f: CommonsFile) -> str:
    who = f.attribution or f.artist or "Unknown author"
    label = f.license_short or ("Public domain" if f.license == "pd" else f.license.upper())
    licence = (
        f'<a href="{escape(f.license_url)}">{escape(label)}</a>' if f.license_url else escape(label)
    )
    return f'{escape(who)} · {licence} · <a href="{escape(f.page_url)}">Wikimedia Commons</a>'


def to_chosen(f: CommonsFile) -> ChosenPhoto:
    return ChosenPhoto(
        key=f"commons:{f.title}",
        filename=commons_filename(f.title),
        url=f.thumb_url,
        credit_html=commons_credit(f),
        source_id=f.title,
        license=f.license,
    )


def choose_breed_photos(
    breed: Breed,
    files: Mapping[str, CommonsFile],
    candidate_files: list[CommonsFile],
    n: int,
) -> tuple[list[ChosenPhoto], bool, list[str]]:
    """Pinned photos first, then candidates (SPEC-v2 6.2).

    `files` holds fresh metadata for the pinned titles. Returns the chosen photos, whether
    the breed is fully reviewed (all photos pinned and still usable), and problems to report.
    """
    chosen: list[ChosenPhoto] = []
    problems = []
    for title in breed.photos:
        f = files.get(title)
        if f is None:
            problems.append(f"{breed.key}: pinned file {title!r} no longer exists")
        elif not is_candidate(f):
            problems.append(
                f"{breed.key}: pinned file {title!r} is no longer usable "
                f"(licence {f.license or 'missing'})"
            )
        elif len(chosen) < n:
            chosen.append(to_chosen(f))
    for f in candidate_files:
        if len(chosen) >= n:
            break
        if f"commons:{f.title}" not in {c.key for c in chosen}:
            chosen.append(to_chosen(f))
    reviewed = bool(breed.photos) and not problems
    return chosen, reviewed, problems
