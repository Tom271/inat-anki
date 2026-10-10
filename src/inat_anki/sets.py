"""Set definitions, species lists and set membership (SPEC-v2 4). Pure: no I/O."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from inat_anki.model import ListedSpecies, Observation, RankedTaxon, SetsConfig, SetSpec

SET_KEYS = {
    "key",
    "name",
    "count",
    "taxon_id",
    "without_taxon_id",
    "exclude_sets",
    "quality_grade",
    "rank",
    "species_list",
    "breed_list",
}
TOP_KEYS = {"place_id", "deck", "photos_per_species", "seen_by", "set"}
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SetsError(ValueError):
    pass


def _ids(value, where: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(i, int) for i in value):
        raise SetsError(f"{where}: expected a list of taxon IDs")
    return tuple(value)


def parse_sets(raw: dict) -> SetsConfig:
    unknown = set(raw) - TOP_KEYS
    if unknown:
        raise SetsError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    sets = []
    for i, s in enumerate(raw.get("set") or []):
        where = f"set {s.get('key', i + 1)}"
        bad = set(s) - SET_KEYS
        if bad:
            raise SetsError(f"{where}: unknown option(s): {', '.join(sorted(bad))}")
        key = s.get("key", "")
        if not KEY_RE.match(key):
            raise SetsError(f"{where}: key must be lower-case letters, digits and dashes")
        sources = [k for k in ("taxon_id", "species_list", "breed_list") if s.get(k)]
        if len(sources) != 1:
            raise SetsError(f"{where}: give exactly one of taxon_id, species_list, breed_list")
        count = s.get("count")
        if "breed_list" in sources:
            if count is not None:
                raise SetsError(f"{where}: breed lists have a fixed order; remove count")
        elif not isinstance(count, int) or count < 1:
            raise SetsError(f"{where}: count must be a positive whole number")
        default_rank = "species,hybrid" if "species_list" in sources else "species"
        sets.append(
            SetSpec(
                key=key,
                name=s.get("name") or key,
                count=count,
                taxon_ids=_ids(s.get("taxon_id"), where),
                without_taxon_ids=_ids(s.get("without_taxon_id"), where),
                exclude_sets=tuple(s.get("exclude_sets") or ()),
                quality_grade=s.get("quality_grade", "research"),
                rank=s.get("rank", default_rank),
                species_list=s.get("species_list"),
                breed_list=s.get("breed_list"),
            )
        )
    keys = [s.key for s in sets]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise SetsError(f"duplicate set key(s): {', '.join(dupes)}")
    for s in sets:
        for ref in s.exclude_sets:
            if ref not in keys or ref == s.key:
                raise SetsError(f"set {s.key}: exclude_sets names unknown set {ref!r}")
    photos = raw.get("photos_per_species", 2)
    if not isinstance(photos, int) or photos < 1:
        raise SetsError("photos_per_species must be a positive whole number")
    return SetsConfig(
        place_id=int(raw.get("place_id", 6857)),
        deck=raw.get("deck", "iNaturalist::UK common species"),
        photos_per_species=photos,
        seen_by=raw.get("seen_by", ""),
        sets=tuple(processing_order(sets)),
    )


def processing_order(sets: list[SetSpec]) -> list[SetSpec]:
    """Sets in file order, except that a set comes after the sets it excludes."""
    by_key = {s.key: s for s in sets}
    done: list[SetSpec] = []
    visiting: set[str] = set()

    def visit(s: SetSpec) -> None:
        if s in done:
            return
        if s.key in visiting:
            raise SetsError(f"exclude_sets forms a cycle through {s.key!r}")
        visiting.add(s.key)
        for ref in s.exclude_sets:
            visit(by_key[ref])
        visiting.discard(s.key)
        done.append(s)

    for s in sets:
        visit(s)
    return done


def parse_species_list(text: str) -> list[ListedSpecies]:
    """Tab-separated: taxon_id, iNat name, listed-as. '#' starts a comment line."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].isdigit():
            raise SetsError(f"species list line {n}: expected taxon_id<TAB>name<TAB>listed as")
        out.append(ListedSpecies(int(parts[0]), parts[1], parts[2]))
    ids = [s.taxon_id for s in out]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise SetsError(f"species list repeats taxon ID(s): {dupes}")
    return out


def rank_candidates(
    ranked: Iterable[RankedTaxon],
    listed_ids: set[int] | None = None,
    excluded: set[int] = frozenset(),
) -> list[RankedTaxon]:
    """Ranked taxa, filtered to a species list if there is one, minus exclusions.

    A list of taxon IDs also matches their descendants (docs/api-notes.md 8), so results
    outside the list are dropped here.
    """
    out, seen = [], set()
    for r in ranked:
        tid = r.taxon.id
        if tid in seen or tid in excluded:
            continue
        if listed_ids is not None and tid not in listed_ids:
            continue
        seen.add(tid)
        out.append(r)
    return out


@dataclass
class Membership:
    members: list[int] = field(default_factory=list)  # in deck order
    added: list[int] = field(default_factory=list)
    below_cutoff: list[int] = field(default_factory=list)  # sticky members outside top N
    removed: list[int] = field(default_factory=list)  # only with rerank


def plan_membership(
    previous: list[int],
    candidates: list[RankedTaxon],
    count: int,
    accepted: Iterable[int],
    rerank: bool = False,
) -> Membership:
    """Members of one set (SPEC-v2 4.2).

    `candidates` are in rank order. `accepted` holds the candidates that have at least one
    usable photo; others are skipped and the next candidate moves up. Members are sticky:
    once in, a taxon stays even if it falls below the top `count`, unless `rerank`.
    """
    accepted = set(accepted)
    top = [c.taxon.id for c in candidates if c.taxon.id in accepted][:count]
    m = Membership()
    if rerank:
        m.members = top
        m.removed = [i for i in previous if i not in top]
    else:
        m.members = list(previous)
        for tid in top:
            if len(m.members) >= max(count, len(previous)):
                break
            if tid not in m.members:
                m.members.append(tid)
        m.below_cutoff = [i for i in previous if i not in top]
    m.added = [i for i in m.members if i not in previous]
    return m


def wanted_candidates(
    previous: list[int], candidates: list[RankedTaxon], count: int, rerank: bool = False
) -> list[RankedTaxon]:
    """Candidates worth searching photos for, in order: enough to fill the set."""
    if rerank:
        return candidates
    return [c for c in candidates if c.taxon.id not in previous][: max(count - len(previous), 0)]


def check_no_overlap(members: Mapping[str, list[int]]) -> None:
    owner: dict[int, str] = {}
    clashes = []
    for set_key, ids in members.items():
        for tid in ids:
            if tid in owner:
                clashes.append(f"taxon {tid} is in both {owner[tid]} and {set_key}")
            owner[tid] = set_key
    if clashes:
        raise SetsError("sets overlap: " + "; ".join(clashes))


def seen_taxa(observations: Iterable[Observation]) -> set[int]:
    """Taxa the user has a research-grade observation of, or of something inside them.

    The caller passes research-grade observations only (as v1's sync fetches them).
    """
    out: set[int] = set()
    for o in observations:
        out.add(o.taxon.id)
        out.update(o.taxon.ancestor_ids)
    return out
