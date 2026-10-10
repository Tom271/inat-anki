"""`inat-anki species`: build the common-species decks (SPEC-v2). Orchestration only."""

import json
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from html import escape
from importlib.resources import files
from pathlib import Path

import requests

from inat_anki import breeds as breeds_mod
from inat_anki import deck, media
from inat_anki import species_state as state_mod
from inat_anki.api import ApiError, INatClient
from inat_anki.commons import CommonsClient
from inat_anki.commons import user_agent as commons_agent
from inat_anki.model import Breed, Card, ChosenPhoto, CommonsFile, RankedTaxon, SetSpec
from inat_anki.normalise import ancestry_from_api, taxon_from_api
from inat_anki.render_species import TAXON_URL, card_hash, card_key, render_card
from inat_anki.selection import choose_photos
from inat_anki.sets import (
    SetsError,
    check_no_overlap,
    parse_sets,
    parse_species_list,
    plan_membership,
    rank_candidates,
    seen_taxa,
    wanted_candidates,
)
from inat_anki.sources import PlaceSpeciesSource, UserObservationsSource
from inat_anki.throttle import Clock, DailyLimitError, RateLimiter, SystemClock, Throttle

POLICY = "shareable"
EXPECTED_PHOTO_BYTES = 250_000
DESCRIPTION = (
    "Photos by iNaturalist users under CC0, CC BY or CC BY-SA, and (for farm breeds) from "
    "Wikimedia Commons under CC0, public domain, CC BY or CC BY-SA, as credited on each "
    "card. Photos under CC BY-SA remain under CC BY-SA. Species data from iNaturalist "
    "(https://www.inaturalist.org). Built with inat-anki."
)


def default_sets_path() -> Path:
    return Path(str(files("inat_anki") / "data" / "uk-common.toml"))


def default_out_name(sets_path: Path, now: float) -> str:
    date = datetime.fromtimestamp(now).date().isoformat()
    name = "UK-common" if sets_path.stem == "uk-common" else sets_path.stem
    return f"iNaturalist-{name}-{date}.apkg"


@dataclass
class SpeciesReport:
    run_at: str
    sets_file: str
    dry_run: bool = False
    sets: dict = field(default_factory=dict)  # key -> {members, added, seen, below_cutoff}
    skipped_no_photos: list[dict] = field(default_factory=list)
    fallbacks: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    removed_search: str = ""
    unreviewed_breeds: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    licences: dict = field(default_factory=dict)
    photos_downloaded: int = 0
    bytes_downloaded: int = 0
    photos_failed: list[dict] = field(default_factory=list)
    deck: str | None = None
    notes_in_deck: int = 0
    deferred: list[str] = field(default_factory=list)
    requests_today: int = 0
    interrupted: bool = False

    def lines(self) -> list[str]:
        from inat_anki.cli import fmt_bytes

        out = ["Sets:"]
        for key, s in self.sets.items():
            extra = f", {s['seen']} seen" if s.get("seen") else ""
            added = f" ({s['added']} new)" if s.get("added") else ""
            out.append(f"  {key:12} {s['members']:>3} cards{added}{extra}")
        out.append(
            f"Photos downloaded:    {self.photos_downloaded} ({fmt_bytes(self.bytes_downloaded)})"
        )
        if self.licences:
            out.append(
                "Photo licences:       "
                + ", ".join(f"{k or 'none'} {v}" for k, v in sorted(self.licences.items()))
            )
        if self.deck:
            out.append(f"Deck written:         {self.deck} ({self.notes_in_deck} notes)")
        out.append(f"API requests today:   {self.requests_today}")
        sections = [
            (
                "Skipped for lack of usable photos:",
                [f"  {s['set']}: {s['name']}" for s in self.skipped_no_photos],
            ),
            (
                "Photos from a fallback search:",
                [f"  {f['set']}: {f['name']} ({f['fallback']})" for f in self.fallbacks],
            ),
            ("Deferred (front photo not downloaded yet):", [f"  {d}" for d in self.deferred]),
            (
                "Breeds with unreviewed photos (run with --suggest-breed-photos):",
                [f"  {b}" for b in self.unreviewed_breeds],
            ),
            ("Problems:", [f"  {p}" for p in self.problems]),
            (
                "Photos that failed to download:",
                [f"  {p['key']}: {p['error']}" for p in self.photos_failed],
            ),
        ]
        for title, rows in sections:
            if rows:
                out += [title, *rows]
        below = [(k, s["below_cutoff"]) for k, s in self.sets.items() if s.get("below_cutoff")]
        if below:
            out.append("Kept although now below the cut-off (sticky; --rerank to rebuild):")
            out += [f"  {k}: {len(ids)}" for k, ids in below]
        if self.removed:
            out += [
                "Removed by --rerank. Importing cannot delete notes; find them with:",
                f"  {self.removed_search}",
            ]
        if self.interrupted:
            out.append("Interrupted: run the same command again to resume.")
        return out


class SpeciesBuild:
    def __init__(self, settings: dict, clock: Clock, sessions, ask, out):
        self.s = settings
        self.clock = clock
        self.ask = ask
        self.out = out
        self.verbose = bool(settings["verbose"])
        self.sets_path = Path(settings["sets"]) if settings["sets"] else default_sets_path()
        raw = tomllib.loads(self.sets_path.read_text())
        self.config = parse_sets(raw)
        self.order = [s["key"] for s in raw.get("set", [])]  # file order, for the decks
        self.cache_dir = Path(settings["cache_dir"])
        self.media_dir = self.cache_dir / "media"
        self.state_path = self.cache_dir / "state.json"
        self.size = settings["photo_size"]
        self.n = self.config.photos_per_species
        self.seen_by = (
            settings["seen_by"] if settings["seen_by"] is not None else self.config.seen_by
        )
        self.st = state_mod.load(self.state_path)
        key = f"place:{self.config.place_id}:{self.sets_path.stem}"
        if self.st.source_key and self.st.source_key != key:
            raise SetsError(
                f"{self.cache_dir} holds the cache for {self.st.source_key}; "
                "use another --cache-dir"
            )
        self.st.source_key = key
        self.st.requests.force = bool(settings["force"])
        limiter = RateLimiter(
            Throttle(settings["interval"], clock),
            daily=self.st.requests,
            bandwidth=self.st.downloads,
            on_pause=lambda sec, why: out(f"Pausing {sec:.0f} s ({why})"),
        )
        retry = lambda sec, why: out(f"{why}; retrying in {sec:.0f} s")  # noqa: E731
        inat_session, commons_session = sessions
        login = self.seen_by or "anonymous"
        self.inat = INatClient(limiter, login, session=inat_session, on_retry=retry)
        self.commons = CommonsClient(
            INatClient(
                limiter, login, session=commons_session, on_retry=retry, agent=commons_agent()
            )
        )
        self.source = PlaceSpeciesSource(self.inat, self.config.place_id)
        self.report = SpeciesReport(
            run_at=datetime.fromtimestamp(clock.time(), UTC).isoformat(timespec="seconds"),
            sets_file=str(self.sets_path),
            dry_run=bool(settings["dry_run"]),
        )
        only = settings["only"]
        self.only = set(only.split(",")) if only else None
        if self.only and self.only - {s.key for s in self.config.sets}:
            raise SetsError(
                f"--only names unknown set(s): "
                f"{', '.join(sorted(self.only - {s.key for s in self.config.sets}))}"
            )

    # ------------------------------------------------------------ helpers

    def log(self, msg: str) -> None:
        if self.verbose:
            self.out(msg)

    def save(self) -> None:
        state_mod.save(self.st, self.state_path)

    def path(self, rel: str) -> Path:
        return self.sets_path.parent / rel

    def wanted(self, set_key: str) -> bool:
        """Whether this run builds the set (--only)."""
        return self.only is None or set_key in self.only

    # ------------------------------------------------------------ species sets

    def search_photos(self, spec: SetSpec, ranked: RankedTaxon, previous=(), previous_obs=None):
        """Photos for one species, with fallbacks (SPEC-v2 6.1 rule 3)."""
        fallbacks = [None] + (["cultivated"] if "casual" in spec.quality_grade else []) + ["world"]
        chosen, used = [], None
        for fb in fallbacks:
            candidates = self.source.photo_candidates(ranked.taxon.id, fb)
            chosen = choose_photos(
                candidates,
                self.n,
                POLICY,
                self.seen_by,
                self.size,
                previous=previous,
                previous_obs=previous_obs,
            )
            if chosen:
                used = fb
                break
        if chosen and used:
            self.report.fallbacks.append(
                {"set": spec.key, "name": ranked.taxon.name, "fallback": used}
            )
        return chosen

    def build_taxon_set(self, spec: SetSpec, excluded: set[int]) -> tuple[list[int], dict, dict]:
        listed = None
        if spec.species_list:
            listed = parse_species_list(self.path(spec.species_list).read_text())
            ids = [s.taxon_id for s in listed]
        else:
            ids = list(spec.taxon_ids)
        ranked = self.source.ranked(spec, ids, spec.count)
        candidates = rank_candidates(
            ranked, {s.taxon_id for s in listed} if listed else None, excluded
        )
        rerank = bool(self.s["rerank"])
        previous = list(self.st.members.get(spec.key, []))
        wanted = wanted_candidates(previous, candidates, spec.count, rerank)
        chosen: dict[int, list[ChosenPhoto]] = {}
        need = spec.count if rerank else max(spec.count - len(previous), 0)
        for cand in wanted:
            if len(chosen) >= need:
                break
            self.log(f"  {spec.key}: searching photos for {cand.taxon.name}")
            photos = self.search_photos(spec, cand)
            if photos:
                chosen[cand.taxon.id] = photos
            else:
                self.report.skipped_no_photos.append({"set": spec.key, "name": cand.taxon.name})
        m = plan_membership(previous, candidates, spec.count, chosen, rerank)
        if m.removed:
            self.report.removed += [{"set": spec.key, "taxon_id": t} for t in m.removed]
        self.report.sets[spec.key] = {
            "members": len(m.members),
            "added": len(m.added),
            "below_cutoff": m.below_cutoff,
        }
        by_id = {c.taxon.id: c for c in candidates}
        return m.members, {t: chosen[t] for t in m.members if t in chosen}, by_id

    def refresh_previous_photos(self, members: dict[str, list], new_photos: dict) -> dict:
        """Re-check earlier choices (licence, still present) with batched lookups."""
        keys = [
            card_key(self.guid(set_key, m))
            for set_key, ms in members.items()
            for m in ms
            if (set_key, m) not in new_photos and self.wanted(set_key)
        ]
        obs_ids = sorted(
            {
                int(c.source_id)
                for k in keys
                for c in self.st.choices.get(k, [])
                if c.key.startswith("inat:")
            }
        )
        titles = sorted(
            {
                c.source_id
                for k in keys
                for c in self.st.choices.get(k, [])
                if c.key.startswith("commons:")
            }
        )
        obs = self.source.observations(obs_ids) if obs_ids else {}
        info = self.commons.file_info(titles) if titles else {}
        return {"obs": obs, "files": info}

    # ------------------------------------------------------------ breeds

    def breed_candidates(self, breed: Breed) -> list[CommonsFile]:
        cat = self.commons.category_files(breed.commons_category)
        found = self.commons.search_files(breed_search(breed))
        return breeds_mod.candidates(cat + found)

    def build_breeds(self, spec: SetSpec, fresh: dict) -> tuple[list[str], dict]:
        breed_list = breeds_mod.parse_breeds(tomllib.loads(self.path(spec.breed_list).read_text()))
        pinned = sorted({t for b in breed_list for t in b.photos})
        pinned_info = self.commons.file_info(pinned) if pinned else {}
        chosen = {}
        for b in breed_list:
            prev = [
                c.source_id
                for c in self.st.choices.get(card_key(self.guid(spec.key, b.key)), [])
                if not self.s["reselect_photos"]
            ]
            if b.photos:
                photos, reviewed, problems = breeds_mod.choose_breed_photos(
                    b, pinned_info, [], self.n
                )
            else:
                photos, reviewed, problems = breeds_mod.choose_breed_photos(
                    replace(b, photos=tuple(prev)), fresh["files"], [], self.n
                )
                problems = []  # unpinned earlier picks may go; that is not a problem
                reviewed = False
            if len(photos) < self.n:
                self.log(f"  breeds: searching Commons for {b.name}")
                more = breeds_mod.choose_breed_photos(
                    replace(b, photos=()), {}, self.breed_candidates(b), self.n
                )[0]
                photos += [p for p in more if p.key not in {x.key for x in photos}]
                photos = photos[: self.n]
            if not reviewed:
                self.report.unreviewed_breeds.append(b.key)
            self.report.problems += problems
            if photos:
                chosen[b.key] = photos
            else:
                self.report.skipped_no_photos.append({"set": spec.key, "name": b.name})
        self.breed_list = {b.key: b for b in breed_list}
        members = [b.key for b in breed_list if b.key in chosen]
        self.report.sets[spec.key] = {
            "members": len(members),
            "added": len([k for k in members if k not in self.st.members.get(spec.key, [])]),
        }
        return members, chosen

    # ------------------------------------------------------------ cards

    def guid(self, set_key: str, member) -> tuple:
        if isinstance(member, str):
            return ("breed", member)
        return ("inat-place", str(self.config.place_id), member)

    def update_taxa(self, member_ids: set[int], ranked: dict[int, RankedTaxon]) -> None:
        for tid, r in ranked.items():
            if tid in member_ids:
                info = self.st.taxa.get(tid)
                self.st.counts[tid] = r.count
                self.st.taxa[tid] = state_mod.TaxonInfo(
                    r.taxon.name,
                    r.taxon.rank,
                    r.taxon.common_name,
                    r.taxon.iconic_taxon_name,
                    info.order if info else None,
                    info.family if info else None,
                )
        missing = sorted(
            t for t in member_ids if t not in self.st.taxa or self.st.taxa[t].family is None
        )
        if missing:
            for d in self.source.taxa(missing):
                t, a = taxon_from_api(d), ancestry_from_api(d)
                self.st.taxa[t.id] = state_mod.TaxonInfo(
                    t.name, t.rank, t.common_name, t.iconic_taxon_name, a.order, a.family
                )

    def card_for(self, spec: SetSpec, member, photos, seen: set[int]) -> Card:
        if isinstance(member, str):
            b = self.breed_list[member]
            return Card(
                guid_parts=self.guid(spec.key, member),
                set_key=spec.key,
                set_name=spec.name,
                sort_id=b.taxon_id,
                common_name=b.name,
                scientific_name=b.species,
                rank="breed",
                family="Suidae" if breeds_mod.breed_kind(b) == "pig" else "Bovidae",
                order="Artiodactyla",
                iconic="Mammalia",
                uk_count=None,
                info_url=breeds_mod.wikipedia_url(b),
                source=f"breed:{b.key}",
                photos=tuple(photos),
                breed_kind=breeds_mod.breed_kind(b),
            )
        info = self.st.taxa[member]
        return Card(
            guid_parts=self.guid(spec.key, member),
            set_key=spec.key,
            set_name=spec.name,
            sort_id=member,
            common_name=info.common_name or "",
            scientific_name=info.name,
            rank=info.rank,
            family=info.family,
            order=info.order,
            iconic=info.iconic,
            uk_count=self.st.counts.get(member),
            info_url=TAXON_URL.format(id=member),
            source=f"place:{self.config.place_id}:{spec.key}",
            photos=tuple(photos),
            seen=member in seen,
        )

    # ------------------------------------------------------------ run

    def suggest_breed_photos(self) -> int:
        spec = next((s for s in self.config.sets if s.breed_list), None)
        if spec is None:
            raise SetsError("the sets file has no breed list")
        breed_list = breeds_mod.parse_breeds(tomllib.loads(self.path(spec.breed_list).read_text()))
        rows = []
        for b in breed_list:
            self.out(f"Commons candidates for {b.name}...")
            rows.append((b, self.breed_candidates(b)))
        page = self.cache_dir / "breed-photos.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(breed_review_html(rows))
        self.out(
            f"Wrote {page}. Pick two photos per breed and copy their `photos = [...]` "
            f"lines into {self.path(spec.breed_list)}."
        )
        return 0

    def run(self) -> int:
        out = self.out
        try:
            if self.s["suggest_breed_photos"]:
                return self.suggest_breed_photos()
            seen: set[int] = set()
            if self.seen_by:
                out(f"Fetching research-grade observations of {self.seen_by} (for 'seen')...")
                user_src = UserObservationsSource(self.inat, self.seen_by, self.config.place_id)
                seen = seen_taxa(user_src.fetch())

            members: dict[str, list] = {}
            new_photos: dict[tuple, list[ChosenPhoto]] = {}
            ranked: dict[int, RankedTaxon] = {}
            listed_ids: dict[str, set[int]] = {}
            breed_spec = None
            for spec in self.config.sets:
                if spec.species_list:
                    listed_ids[spec.key] = {
                        s.taxon_id
                        for s in parse_species_list(self.path(spec.species_list).read_text())
                    }
                if self.only and spec.key not in self.only:
                    members[spec.key] = list(self.st.members.get(spec.key, []))
                    continue
                if spec.breed_list:
                    breed_spec = spec
                    continue  # breeds need the re-check data; built below
                excluded = set()
                for ref in spec.exclude_sets:
                    excluded |= listed_ids.get(ref) or set(members.get(ref, []))
                out(f"Ranking {spec.name}...")
                ids, photos, by_id = self.build_taxon_set(spec, excluded)
                members[spec.key] = ids
                ranked.update(by_id)
                for tid, p in photos.items():
                    new_photos[(spec.key, tid)] = p
            check_no_overlap({k: [m for m in v if isinstance(m, int)] for k, v in members.items()})

            out("Re-checking earlier photo choices...")
            # Breeds are chosen after this, so include their earlier members in the re-check.
            to_check = dict(members)
            if breed_spec:
                to_check[breed_spec.key] = list(self.st.members.get(breed_spec.key, []))
            fresh = self.refresh_previous_photos(to_check, new_photos)
            if breed_spec:
                out("Choosing farm breed photos...")
                ids, photos = self.build_breeds(breed_spec, fresh)
                members[breed_spec.key] = ids
                for k, p in photos.items():
                    new_photos[(breed_spec.key, k)] = p

            taxon_members = {m for ms in members.values() for m in ms if isinstance(m, int)}
            self.update_taxa(taxon_members, ranked)
            self.save()

            # Photos for sticky members: keep valid earlier choices, top up if needed.
            spec_by_key = {s.key: s for s in self.config.sets}
            all_photos: dict[tuple, list[ChosenPhoto]] = {}
            for set_key, ms in members.items():
                if not self.wanted(set_key):
                    continue
                spec = spec_by_key[set_key]
                for m in ms:
                    if (set_key, m) in new_photos:
                        all_photos[(set_key, m)] = new_photos[(set_key, m)]
                        continue
                    if isinstance(m, str):
                        continue  # breed photos were all chosen in build_breeds
                    prev = (
                        []
                        if self.s["reselect_photos"]
                        else self.st.choices.get(card_key(self.guid(set_key, m)), [])
                    )
                    prev_obs = {
                        c.source_id: fresh["obs"][c.source_id]
                        for c in prev
                        if c.source_id in fresh["obs"]
                    }
                    photos = choose_photos(
                        [],
                        self.n,
                        POLICY,
                        self.seen_by,
                        self.size,
                        previous=[c.key for c in prev],
                        previous_obs=prev_obs,
                    )
                    if len(photos) < self.n:
                        info = self.st.taxa[m]
                        rt = RankedTaxon(
                            taxon_from_api({"id": m, "name": info.name, "rank": info.rank}), 0
                        )
                        photos = (
                            self.search_photos(
                                spec, rt, previous=[p.key for p in photos], previous_obs=prev_obs
                            )
                            or photos
                        )
                    if photos:
                        all_photos[(set_key, m)] = photos
                    else:
                        self.report.problems.append(
                            f"{set_key}: {self.st.taxa[m].name} has "
                            "no usable photo any more; card left out"
                        )

            cards = {
                (k, m): self.card_for(spec_by_key[k], m, p, seen)
                for (k, m), p in all_photos.items()
            }
            for k in members:
                if k in self.report.sets:
                    self.report.sets[k]["seen"] = sum(
                        1 for (sk, _), c in cards.items() if sk == k and c.seen
                    )
            notes = {key: render_card(c) for key, c in cards.items()}
            if self.report.removed:
                ids = " or ".join(f"TaxonID:{r['taxon_id']}" for r in self.report.removed)
                self.report.removed_search = f'"deck:{self.config.deck}::*" ({ids})'

            # Downloads.
            cached_ok = media.scan_cache(self.media_dir, self.st.photos)
            wanted: dict[str, ChosenPhoto] = {}
            fronts, extras = [], []
            for photos in all_photos.values():
                for i, p in enumerate(photos):
                    rec = self.st.photos.get(p.key)
                    if p.key in wanted or (
                        p.key in cached_ok
                        and rec
                        and rec.size == self.size
                        and not self.s["refresh_photos"]
                    ):
                        continue
                    wanted[p.key] = p
                    (fronts if i == 0 else extras).append(p)
            downloads = fronts + extras
            if self.s["max_downloads"] is not None:
                downloads = downloads[: self.s["max_downloads"]]
            self.report.licences = dict(
                Counter(p.license for ps in all_photos.values() for p in ps)
            )
            out(
                f"{sum(len(v) for v in members.values())} cards; "
                f"{len(downloads)} photos to download"
            )
            if self.s["dry_run"]:
                return self.finish()
            big = len(downloads) > self.s["warn_threshold"] and not self.s["yes"]
            if big and self.ask(
                f"Download {len(downloads)} photos (about "
                f"{len(downloads) * EXPECTED_PHOTO_BYTES / 1e6:.0f} MB, "
                f"{len(downloads) * self.s['interval'] / 60:.0f} min)? [y/N] "
            ).strip().lower() not in ("y", "yes"):
                out("Cancelled.")
                return 1

            def on_saved(p, record):
                self.st.photos[p.key] = record
                self.save()
                self.report.photos_downloaded += 1
                self.report.bytes_downloaded += record.bytes
                n = self.report.photos_downloaded
                if self.verbose or n % 10 == 0 or n == len(downloads):
                    out(f"  {n}/{len(downloads)} photos")

            def on_failed(p, error):
                self.report.photos_failed.append({"key": p.key, "error": str(error)})

            # Commons files go through the Commons client, for Wikimedia's User-Agent policy.
            for client, prefix in ((self.inat, "inat:"), (self.commons.http, "commons:")):
                media.download_chosen(
                    client,
                    [p for p in downloads if p.key.startswith(prefix)],
                    self.size,
                    self.media_dir,
                    EXPECTED_PHOTO_BYTES,
                    on_saved,
                    on_failed,
                )
            self.st.photo_size = self.size

            # Package.
            referenced = {m for n in notes.values() for m in n.media}
            available = media.available_media(self.media_dir, referenced)
            decks = []
            for spec in sorted(self.config.sets, key=lambda s: self.order.index(s.key)):
                if not self.wanted(spec.key):
                    continue
                ready = []
                for m in members.get(spec.key, []):
                    note = notes.get((spec.key, m))
                    if note is None:
                        continue
                    if note.front_media in available:
                        ready.append(note)
                    else:
                        self.report.deferred.append(f"{spec.key}: {m}")
                if ready:
                    decks.append((spec.key, f"{self.config.deck}::{spec.name}", ready))
            out_path = Path(self.s["out"] or default_out_name(self.sets_path, self.clock.time()))
            if decks:
                deck.build_species_package(decks, DESCRIPTION, self.media_dir, out_path)
                self.report.deck = str(out_path)
                self.report.notes_in_deck = sum(len(n) for _, _, n in decks)

            # Remember what went in (empty hash = rebuild next run when extras arrive).
            packaged = {(k, m) for k, _, ns in decks for m in members.get(k, [])}
            for (k, m), note in notes.items():
                if (k, m) not in packaged or note.front_media not in available:
                    continue
                ck = card_key(note.guid_parts)
                complete = all(x in available for x in note.media)
                self.st.notes[ck] = card_hash(note) if complete else ""
                self.st.choices[ck] = [
                    state_mod.Choice(p.key, p.source_id) for p in all_photos[(k, m)]
                ]
            for k, ms in members.items():
                if self.wanted(k):
                    self.st.members[k] = ms
            if self.s["prune"]:
                keep = {p.key for ps in all_photos.values() for p in ps}
                gone = [k for k in self.st.photos if k not in keep]
                media.prune(self.media_dir, [self.st.photos[k].filename for k in gone])
                for k in gone:
                    del self.st.photos[k]
            self.save()
            return self.finish()
        except KeyboardInterrupt:
            self.report.interrupted = True
            self.save()
            self.finish()
            return 130
        except (ApiError, DailyLimitError, requests.RequestException) as e:
            self.save()
            out(f"Error: {e}")
            self.finish()
            return 1

    def finish(self) -> int:
        self.report.requests_today = self.st.requests.used_today(self.clock.time())
        self.out("")
        for line in self.report.lines():
            self.out(line)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "last-run.json").write_text(
            json.dumps(asdict(self.report), indent=2, ensure_ascii=False) + "\n"
        )
        return 0


def breed_search(breed: Breed) -> str:
    return breeds_mod.search_phrase(breed)


def breed_review_html(rows: list[tuple[Breed, list[CommonsFile]]]) -> str:
    """A local page for choosing breed photos: thumbnails, credits and TOML to copy."""
    parts = [
        "<!doctype html><meta charset=utf-8><title>Breed photo review</title><style>",
        "body{font:15px system-ui;margin:16px;max-width:1200px}"
        "section{margin-bottom:32px}.grid{display:grid;"
        "grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}"
        "figure{margin:0}img{width:100%;height:180px;object-fit:cover;border-radius:6px}"
        "figcaption{font-size:12px;color:#555;word-break:break-word}"
        "code{display:block;font-size:12px;background:#f3f3f3;padding:4px;margin-top:4px;"
        "user-select:all}</style>",
        "<h1>Breed photo review</h1><p>Choose two photos per breed. Copy the line under a "
        "photo into that breed's <code style=display:inline>photos = [ ... ]</code> list "
        "in the breeds file.</p>",
    ]
    for breed, files_ in rows:
        parts.append(
            f"<section><h2>{escape(breed.name)} <small>({escape(breed.key)}, "
            f"{len(files_)} candidates)</small></h2><div class=grid>"
        )
        for f in files_:
            parts.append(
                f'<figure><a href="{escape(f.page_url)}"><img loading=lazy '
                f'src="{escape(f.thumb_url)}"></a><figcaption>'
                f"{breeds_mod.commons_credit(f)}<code>{escape(json.dumps(f.title))},"
                "</code></figcaption></figure>"
            )
        parts.append("</div></section>")
    return "\n".join(parts)


def species(
    settings: dict,
    clock: Clock | None = None,
    sessions=(None, None),
    ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    return SpeciesBuild(settings, clock or SystemClock(), sessions, ask, out).run()
