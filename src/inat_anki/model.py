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
    ancestor_ids: tuple[int, ...] = ()


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


# ---------------------------------------------------------------- v2: common-species decks

# Fields of the "iNaturalist species" note type, in order. Never reorder, rename or remove
# them (SPEC-v2 5.1).
SPECIES_FIELD_NAMES = (
    "TaxonID",
    "FrontPhoto",
    "ExtraPhotos",
    "CommonName",
    "ScientificName",
    "Rank",
    "Group",
    "Family",
    "Order",
    "UKObservations",
    "InfoURL",
    "PhotoCredits",
    "Source",
)
GUID_NAMESPACE_PLACE = "inat-place"
GUID_NAMESPACE_BREED = "breed"


@dataclass(frozen=True)
class SetSpec:
    """One subdeck of the species deck (SPEC-v2 4)."""

    key: str
    name: str
    count: int | None = None  # None for breed lists, whose order is fixed
    taxon_ids: tuple[int, ...] = ()
    without_taxon_ids: tuple[int, ...] = ()
    exclude_sets: tuple[str, ...] = ()
    quality_grade: str = "research"
    rank: str = "species"
    species_list: str | None = None
    breed_list: str | None = None


@dataclass(frozen=True)
class SetsConfig:
    place_id: int
    deck: str
    photos_per_species: int
    seen_by: str
    sets: tuple[SetSpec, ...]


@dataclass(frozen=True)
class ListedSpecies:
    taxon_id: int
    name: str
    listed_as: str


@dataclass(frozen=True)
class RankedTaxon:
    taxon: Taxon
    count: int


@dataclass(frozen=True)
class Breed:
    key: str
    name: str
    species: str
    taxon_id: int
    commons_category: str
    wikipedia: str
    photos: tuple[str, ...] = ()  # pinned Commons file titles
    search: str = ""  # Commons search phrase; default "<name> <kind>"


@dataclass(frozen=True)
class CommonsFile:
    title: str  # "File:..."
    thumb_url: str
    width: int
    height: int
    mime: str
    license: str  # extmetadata License, e.g. "cc-by-sa-4.0"; "" if missing
    license_short: str
    license_url: str
    artist: str  # plain text
    attribution: str  # plain text; "" if none
    restrictions: str
    page_url: str


@dataclass(frozen=True)
class ChosenPhoto:
    """A photo chosen for a species or breed card, with its credit line."""

    key: str  # "inat:<photo id>" or "commons:<file title>"
    filename: str
    url: str
    credit_html: str
    source_id: str  # iNat observation ID, or the Commons file title
    license: str = ""  # iNat licence code or Commons licence value, for reports


@dataclass(frozen=True)
class Card:
    """Everything needed to render one species or breed note."""

    guid_parts: tuple
    set_key: str
    set_name: str
    sort_id: int
    common_name: str
    scientific_name: str
    rank: str
    family: str | None
    order: str | None
    iconic: str | None
    uk_count: int | None
    info_url: str
    source: str
    photos: tuple[ChosenPhoto, ...]
    seen: bool = False
    breed_kind: str | None = None  # "cattle", "sheep" or "pig" for breed cards


@dataclass(frozen=True)
class CardNote:
    guid_parts: tuple
    set_key: str
    fields: tuple[str, ...]
    tags: tuple[str, ...]
    front_media: str
    media: tuple[str, ...]

    def field(self, name: str) -> str:
        return self.fields[SPECIES_FIELD_NAMES.index(name)]
