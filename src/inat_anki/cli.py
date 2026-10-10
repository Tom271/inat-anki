"""Build an Anki deck from your research-grade iNaturalist observations."""

import argparse
import json
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import requests

from inat_anki import __version__, deck, media
from inat_anki import state as state_mod
from inat_anki.api import ApiError, INatClient
from inat_anki.model import ObsRecord
from inat_anki.normalise import PHOTO_SIZES
from inat_anki.plan import make_plan, split_ready
from inat_anki.render import anki_search, note_hash, render
from inat_anki.sources import UserObservationsSource, fetch_ancestries
from inat_anki.throttle import (
    Clock,
    DailyLimitError,
    RateLimiter,
    RateTooHighError,
    SystemClock,
    Throttle,
    interval_for_rate,
)

CONFIG_FILE = "inat-anki.toml"
UK_PLACE_ID = 6857  # "United Kingdom"; see docs/api-notes.md

DEFAULTS = {
    "user": None,
    "out": "iNaturalist.apkg",
    "cache_dir": "inat-cache",
    "photo_size": "large",
    "refresh_photos": False,
    "changed_only": False,
    "prune": False,
    "warn_threshold": 200,
    "max_downloads": None,
    "yes": False,
    "rate": 1.0,
    "dry_run": False,
    "verbose": False,
    "force": False,
    "place_id": UK_PLACE_ID,
    "locale": "en",
}


class UsageError(Exception):
    pass


# ---------------------------------------------------------------- arguments and config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inat-anki", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser(
        "sync",
        help="fetch observations, download new photos and write the deck",
        description="Fetch observations, download new photos and write the deck. "
        f"Settings can also come from {CONFIG_FILE}; flags override it.",
    )
    # Defaults are None so we can tell which flags were given; DEFAULTS fills the rest.
    sync.add_argument("--user", help="iNaturalist login")
    sync.add_argument("--out", help=f"output .apkg (default {DEFAULTS['out']})")
    sync.add_argument(
        "--cache-dir", help=f"photo cache and state (default {DEFAULTS['cache_dir']})"
    )
    sync.add_argument("--photo-size", choices=PHOTO_SIZES, help="default large")
    sync.add_argument(
        "--refresh-photos",
        action="store_true",
        default=None,
        help="re-download all referenced photos",
    )
    sync.add_argument(
        "--changed-only",
        action="store_true",
        default=None,
        help="write only new and changed notes to the .apkg",
    )
    sync.add_argument(
        "--prune",
        action="store_true",
        default=None,
        help="delete cached photos no longer referenced",
    )
    sync.add_argument(
        "--warn-threshold",
        type=int,
        help="ask before downloading more photos than this (default 200)",
    )
    sync.add_argument(
        "--max-downloads",
        type=int,
        help="download at most this many photos; the rest wait for the next run",
    )
    sync.add_argument(
        "--yes", "-y", action="store_true", default=None, help="do not ask for confirmation"
    )
    sync.add_argument("--rate", type=float, help="requests per second (default 1.0, max 1.1)")
    sync.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="fetch metadata and print the plan; no downloads, no deck",
    )
    sync.add_argument(
        "--force",
        action="store_true",
        default=None,
        help="allow more than 11,000 requests in one UTC day",
    )
    sync.add_argument("--config", type=Path, help=f"config file (default ./{CONFIG_FILE})")
    sync.add_argument("--verbose", "-v", action="store_true", default=None)
    return parser


def load_config(path: Path | None) -> dict:
    explicit = path is not None
    path = path or Path(CONFIG_FILE)
    if not path.exists():
        if explicit:
            raise UsageError(f"config file {path} not found")
        return {}
    with path.open("rb") as f:
        raw = tomllib.load(f)
    config = {k.replace("-", "_"): v for k, v in raw.items()}
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise UsageError(f"unknown setting(s) in {path}: {', '.join(sorted(unknown))}")
    return config


def resolve_settings(args: argparse.Namespace) -> dict:
    settings = {**DEFAULTS, **load_config(args.config)}
    settings.update({k: v for k, v in vars(args).items() if k in DEFAULTS and v is not None})
    if not settings["user"]:
        raise UsageError(f"no user given: pass --user or set user in {CONFIG_FILE}")
    if settings["photo_size"] not in PHOTO_SIZES:
        raise UsageError(f"photo_size must be one of {', '.join(PHOTO_SIZES)}")
    try:
        settings["interval"] = interval_for_rate(float(settings["rate"]))
    except RateTooHighError as e:
        raise UsageError(str(e)) from e
    return settings


# ---------------------------------------------------------------- report


@dataclass
class Report:
    run_at: str
    source: str
    dry_run: bool = False
    observations_fetched: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    removed: list[int] = field(default_factory=list)
    removed_search: str = ""
    skipped: list[dict] = field(default_factory=list)
    photos_downloaded: int = 0
    bytes_downloaded: int = 0
    photos_failed: list[dict] = field(default_factory=list)
    photos_pruned: int = 0
    deck: str | None = None
    notes_in_deck: int = 0
    requests_today: int = 0
    interrupted: bool = False

    def lines(self) -> list[str]:
        out = [
            f"Observations fetched: {self.observations_fetched} "
            f"({self.new} new, {self.changed} changed, {self.unchanged} unchanged, "
            f"{len(self.removed)} removed)",
            f"Photos downloaded:    {self.photos_downloaded} ({fmt_bytes(self.bytes_downloaded)})",
        ]
        if self.photos_pruned:
            out.append(f"Photos pruned:        {self.photos_pruned}")
        if self.deck:
            out.append(f"Deck written:         {self.deck} ({self.notes_in_deck} notes)")
        elif not self.dry_run:
            out.append("Deck written:         none (nothing to write)")
        out.append(f"API requests today:   {self.requests_today}")
        if self.skipped:
            out.append("Skipped observations:")
            out += [f"  {s['obs_id']}: {s['reason']}" for s in self.skipped]
        if self.photos_failed:
            out.append("Photos that failed to download:")
            out += [
                f"  photo {p['photo_id']} (obs {p['obs_id']}): {p['error']}"
                for p in self.photos_failed
            ]
        if self.removed:
            out += [
                "Removed observations (deleted, or no longer research grade):",
                "  Importing cannot delete notes, so remove them in Anki's browser with:",
                f"  {self.removed_search}",
            ]
        if self.interrupted:
            out.append("Interrupted: run the same command again to resume.")
        return out


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.2f} GB"


def fmt_duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


# ---------------------------------------------------------------- sync


def sync(
    settings: dict,
    clock: Clock | None = None,
    session: requests.Session | None = None,
    ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    clock = clock or SystemClock()
    verbose = settings["verbose"]
    login = settings["user"]
    cache_dir = Path(settings["cache_dir"])
    media_dir = cache_dir / "media"
    state_path = cache_dir / "state.json"
    size = settings["photo_size"]

    st = state_mod.load(state_path)
    source_key = f"user:{login}"
    if st.source_key and st.source_key != source_key:
        raise UsageError(
            f"{cache_dir} holds the cache for {st.source_key}; use another --cache-dir"
        )
    st.source_key = source_key
    st.requests.force = bool(settings["force"])

    limiter = RateLimiter(
        Throttle(settings["interval"], clock),
        daily=st.requests,
        bandwidth=st.downloads,
        on_pause=lambda s, why: out(f"Pausing {fmt_duration(s)} ({why})"),
    )
    client = INatClient(
        limiter,
        login,
        session=session,
        on_retry=lambda s, why: out(f"{why}; retrying in {fmt_duration(s)}"),
    )
    source = UserObservationsSource(client, login, settings["place_id"], settings["locale"])
    report = Report(
        run_at=datetime.fromtimestamp(clock.time(), UTC).isoformat(timespec="seconds"),
        source=source_key,
        dry_run=bool(settings["dry_run"]),
    )

    def save_state() -> None:
        state_mod.save(st, state_path)

    try:
        # 1. Fetch metadata.
        out(f"Fetching research-grade observations of {login}...")
        observations = source.fetch()
        report.observations_fetched = len(observations)
        st.taxa.update(
            fetch_ancestries(
                client,
                {o.taxon.id for o in observations},
                st.taxa,
                settings["locale"],
                settings["place_id"],
            )
        )
        save_state()

        # 2-3. Render and plan.
        notes = {
            o.id: render(o, st.taxa.get(o.taxon.id), source_key) for o in observations if o.photos
        }
        cached_ok = media.scan_cache(media_dir, st.photos)
        plan = make_plan(
            observations,
            notes,
            st.observations,
            st.photos,
            cached_ok,
            size,
            refresh=bool(settings["refresh_photos"]),
            min_interval=settings["interval"],
        )
        report.new, report.changed, report.unchanged = (
            len(plan.new),
            len(plan.changed),
            len(plan.unchanged),
        )
        report.removed = plan.removed
        report.removed_search = anki_search(plan.removed)
        report.skipped = [{"obs_id": i, "reason": "no photos"} for i in plan.skipped_no_photos]

        downloads = plan.downloads
        if settings["max_downloads"] is not None:
            downloads = downloads[: settings["max_downloads"]]
        per_photo = plan.estimated_bytes / len(plan.downloads) if plan.downloads else 0
        out(
            f"{len(observations)} observations: {len(plan.new)} new, {len(plan.changed)} "
            f"changed, {len(plan.unchanged)} unchanged, {len(plan.removed)} removed"
        )
        if downloads:
            out(
                f"{len(downloads)} photos to download ({size}), about "
                f"{fmt_bytes(per_photo * len(downloads))}, about "
                f"{fmt_duration(len(downloads) * settings['interval'])}"
            )
            if len(downloads) < len(plan.downloads):
                out(
                    f"  ({len(plan.downloads) - len(downloads)} more left for later runs "
                    "by --max-downloads)"
                )

        if settings["dry_run"]:
            return finish(report, st, cache_dir, out, clock)

        # 4. Confirm.
        if len(downloads) > settings["warn_threshold"] and not settings["yes"]:
            if not sys.stdin.isatty() and ask is input:
                raise UsageError("large download needs confirmation: pass --yes")
            if ask("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                out("Cancelled.")
                return 1

        # 5. Download, saving state after every photo.
        photos_by_id = {p.id: p for o in observations for p in o.photos}

        def on_saved(d, record):
            st.photos[d.photo_id] = record
            save_state()
            report.photos_downloaded += 1
            report.bytes_downloaded += record.bytes
            n = report.photos_downloaded
            if verbose:
                out(f"  [{n}/{len(downloads)}] {record.filename} ({fmt_bytes(record.bytes)})")
            elif n % 10 == 0 or n == len(downloads):
                out(f"  {n}/{len(downloads)} photos")

        def on_failed(d, error):
            report.photos_failed.append(
                {"photo_id": d.photo_id, "obs_id": d.obs_id, "error": str(error)}
            )
            out(f"  photo {d.photo_id} failed: {error}")

        media.download_all(
            client, downloads, photos_by_id, size, media_dir, round(per_photo), on_saved, on_failed
        )
        st.photo_size = size

        # 6-7. Package what is ready.
        referenced = {m for n in notes.values() for m in n.media}
        available = media.available_media(media_dir, referenced)
        ready, deferred = split_ready(notes, available)
        report.skipped += [
            {"obs_id": i, "reason": "front photo not downloaded yet"} for i in deferred
        ]
        if settings["changed_only"]:
            wanted = set(plan.new) | set(plan.changed)
            to_package = [i for i in ready if i in wanted]
        else:
            to_package = ready

        out_path = Path(settings["out"])
        if to_package:
            deck.build_package([notes[i] for i in to_package], media_dir, out_path)
            report.deck, report.notes_in_deck = str(out_path), len(to_package)

        # Remember what went into the deck. A note packaged without all its extra photos
        # gets an empty hash, so the next run sees it as changed and rebuilds it.
        obs_by_id = {o.id: o for o in observations}
        for i in to_package:
            o, note = obs_by_id[i], notes[i]
            complete = all(m in available for m in note.media)
            st.observations[i] = ObsRecord(
                o.updated_at, tuple(p.id for p in o.photos), note_hash(note) if complete else ""
            )
        for i in plan.removed:
            st.observations.pop(i, None)

        if settings["prune"]:
            names = [st.photos[i].filename for i in plan.unreferenced_photos]
            media.prune(media_dir, names)
            for i in plan.unreferenced_photos:
                del st.photos[i]
            report.photos_pruned = len(names)
        save_state()
        return finish(report, st, cache_dir, out, clock)

    except KeyboardInterrupt:
        report.interrupted = True
        save_state()
        finish(report, st, cache_dir, out, clock)
        return 130
    except (ApiError, DailyLimitError, requests.RequestException) as e:
        save_state()
        out(f"Error: {e}")
        finish(report, st, cache_dir, out, clock)
        return 1


def finish(report: Report, st, cache_dir: Path, out, clock: Clock) -> int:
    report.requests_today = st.requests.used_today(clock.time())
    out("")
    for line in report.lines():
        out(line)
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_mod.write_atomic(
        cache_dir / "last-run.json",
        (json.dumps(report.__dict__, indent=2) + "\n").encode(),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = resolve_settings(args)
        return sync(settings)
    except (UsageError, state_mod.StateError) as e:
        print(f"inat-anki: {e}", file=sys.stderr)
        return 2
