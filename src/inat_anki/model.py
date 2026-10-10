"""Plain data types shared by every module. Pure: no I/O."""

from dataclasses import dataclass, field

DECK_NAME = "iNaturalist::My observations"
GUID_NAMESPACE_OBS = "inat-obs"

# The note type's fields, in order. Never reorder, rename or remove them: Anki would treat
# the next import as a schema change (SPEC 7.2).
FIELD_NAMES = (
    "ObsID",
    "FrontPhoto",
    "ExtraPhotos",
    "CommonName",
    "ScientificName",
    "Rank",
    "ObservedOn",
    "Place",
    "Coordinates",
    "ObsURL",
    "TaxonID",
    "Source",
    "PhotoCredits",
)


@dataclass(frozen=True)
class Photo:
    id: int
    url: str  # the `square` URL exactly as the API returns it
    license_code: str | None  # None means all rights reserved
    attribution: str


@dataclass(frozen=True)
class Taxon:
    id: int
    name: str
    rank: str
    common_name: str | None
    iconic_taxon_name: str | None


@dataclass(frozen=True)
class TaxonAncestry:
    """Higher taxonomy of one taxon, used for tags. Cached in state."""

    taxon_id: int
    order: str | None
    family: str | None


@dataclass(frozen=True)
class Observation:
    id: int
    user_login: str
    taxon: Taxon
    photos: tuple[Photo, ...]
    observed_on: str | None  # local date, "YYYY-MM-DD"
    time_observed_at: str | None  # ISO 8601 with the local offset in effect at the time
    place_guess: str | None
    latitude: float | None
    longitude: float | None
    accuracy_m: int | None  # public positional accuracy
    obscured: bool
    updated_at: str


@dataclass(frozen=True)
class Note:
    """One rendered Anki note: field values in FIELD_NAMES order, tags and media."""

    obs_id: int
    fields: tuple[str, ...]
    tags: tuple[str, ...]
    front_media: str
    media: tuple[str, ...]  # every media filename the note references, front photo first

    def field(self, name: str) -> str:
        return self.fields[FIELD_NAMES.index(name)]


@dataclass(frozen=True)
class ObsRecord:
    """What state.json remembers about one observation that went into a deck."""

    updated_at: str
    photo_ids: tuple[int, ...]
    note_hash: str


@dataclass(frozen=True)
class PhotoRecord:
    """What state.json remembers about one cached photo."""

    filename: str
    size: str  # "large" or "medium"
    bytes: int
    license_code: str | None
    attribution: str
    sha256: str


@dataclass(frozen=True)
class PhotoDownload:
    photo_id: int
    obs_id: int
    url: str
    filename: str
    is_front: bool


@dataclass
class Plan:
    new: list[int] = field(default_factory=list)
    changed: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    skipped_no_photos: list[int] = field(default_factory=list)
    downloads: list[PhotoDownload] = field(default_factory=list)
    unreferenced_photos: list[int] = field(default_factory=list)
    estimated_bytes: int = 0
    estimated_seconds: float = 0.0
