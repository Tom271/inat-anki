# inat-anki: build specification (v1, Python CLI)

## 1. Purpose

Generate an Anki deck (`.apkg`) from a user's research-grade iNaturalist observations, so the user can learn to recognise species they have personally seen. Each observation becomes one card. The front shows a photo; the back shows the identification and observation details.

The tool must be **re-runnable**. Re-runs download only photos it has not already cached, and the resulting deck must re-import into Anki without creating duplicates or losing review history.

v1 is a local Python command-line tool. A browser web app comes later, so the code must be structured to port cleanly (see section 11).

## 2. Verify before building

These points are believed correct but **must be checked against the live API before the code depends on them**. Record what you find in `docs/api-notes.md`.

1. **UK place ID.** I believe "United Kingdom" is place `6857`. Confirm with `GET /v1/places/autocomplete?q=United Kingdom`. Make it a config value, not a magic number.
2. **Common-name resolution.** iNat picks a common name in this order: a name tied to the preferred place, then the locale's top name, then a global name. Confirm that `locale=en&preferred_place_id=<UK>` on `/v1/observations` returns British names in `taxon.preferred_common_name`. Test it on, for example, *Erithacus rubecula* (should be "European Robin" or "Robin") and *Larus argentatus*.
3. **Photo URL sizes.** `photos[].url` is the `square` size. Confirm that replacing `square` with `medium` (about 500 px) or `large` (about 1024 px) works on both photo hosts, `inaturalist-open-data.s3.amazonaws.com` and `static.inaturalist.org`.
4. **Photo licence fields.** Confirm that `photos[].license_code` is `null` for "all rights reserved", and that `photos[].attribution` is populated.
5. **Time fields.** Confirm the format of `time_observed_at` (expected: ISO 8601 with offset) and of `observed_time_zone`.
6. **Obscured locations.** Confirm what the unauthenticated API returns for obscured or private observations (`obscured`, `geoprivacy`, `taxon_geoprivacy`, `place_guess`, `location`).

## 3. Functional requirements

| ID | Requirement |
|----|-------------|
| R1 | Every **research-grade** observation of the user gets a card. |
| R2 | Every card has a **photo on the front**. Observations without photos (for example, sound-only) are skipped and listed in the run report. |
| R3 | The back shows the **common name** (UK English), the **scientific name in italics** below it, and the observation's **date** and **location**. |
| R4 | All cards go into **one deck**, regardless of taxon. Taxonomy is stored as **tags** so filtered decks are possible in Anki now and filtering is easy to add to the tool later. |
| R5 | (Future, do not implement) Build a deck from a **location** across all taxa, to learn local wildlife before a trip. The v1 design must not preclude it (see section 10). |
| R6 | **Re-runnable and incremental.** Photos are cached and downloaded only if new, missing or corrupt, unless the user passes `--refresh-photos`. New observations and observations that have become research grade are picked up automatically. |
| R7 | **Rate limits:** respect iNat's recommended limits with at most +10% tolerance (section 6). |
| R8 | **Large-run warning:** before downloading, estimate the size and time. If it is above a threshold, warn and ask for confirmation. Large runs must be resumable after interruption. |
| R9 | **One card per observation**, not per species. The back layout is the same for every card; only the per-observation data differs. |
| R10 | **Respect all licences** (section 8). |
| R11 | The repository uses the **MIT licence**. |

## 4. Technology

- Python 3.11+, managed with **uv**. Use no other tooling (no pip, Poetry or virtualenv commands):
  - scaffold with `uv init --package inat-anki`;
  - add dependencies with `uv add` and dev dependencies with `uv add --dev`;
  - commit `uv.lock`, and pin the Python version in `.python-version`;
  - run with `uv run inat-anki ...`, test with `uv run pytest`, lint with `uv run ruff check`;
  - in the README, document `uv tool install .` for a global command.
- Dependencies: `requests` (Apache-2.0) and `genanki` (MIT). Both are compatible with MIT. Do not add `pyinaturalist`: calling the REST endpoints directly keeps the logic identical to what the JavaScript web app will do.
- Dev dependencies: `pytest`, `responses` (or `requests-mock`), `ruff`.
- Packaging: `pyproject.toml` with a console entry point `inat-anki`.
- **Any future JavaScript frontend uses Svelte** (see section 11).

## 5. Data flow

```
1. Fetch metadata   GET /v1/observations (all RG obs of the user, paged)
2. Normalise        API JSON -> Observation / Photo dataclasses (pure)
3. Plan             diff against state.json -> photos to download, notes new/changed/removed (pure)
4. Confirm          if the plan exceeds thresholds -> warn, prompt (skip with --yes)
5. Download         throttled, resumable, writes cache after each photo
6. Render           Observation -> note fields (pure)
7. Package          genanki -> .apkg containing all current notes and their media
8. Report           summary printed and written to cache/last-run.json
```

### 5.1 Fetching observations

`GET https://api.inaturalist.org/v1/observations` with these parameters:

- `user_login=<username>`
- `quality_grade=research`
- `per_page=200` (the maximum)
- `order_by=id&order=asc`, paging with `id_above=<last id>` rather than `page`. This handles more than 10k results, which `page` cannot.
- `locale=en&preferred_place_id=<UK place id>`

Fetch the **full** list every run rather than using `updated_since`. It costs `ceil(n/200)` requests (1 request for 154 observations), and it is the only way to detect observations that are **no longer** research grade or have been deleted. `updated_since` cannot report removals.

Set a `User-Agent` header: `inat-anki/<version> (<username>)`. iNat asks clients to identify themselves.

### 5.2 Change detection

`state.json` stores, per observation: `updated_at`, the photo IDs in order, and a hash of the rendered note fields. Per photo, it stores: filename, size, licence, attribution and sha256.

- **New observation:** an ID not in state.
- **Changed observation:** the fields hash differs. This catches taxon changes, a new common name, and edited date or place.
- **Removed observation:** in state but absent from the fetch.
- **Photos to download:** referenced photo IDs that are not cached, or whose file is missing or fails its sha256 check. Photos are keyed by photo ID; a re-uploaded photo gets a new ID.
- `--refresh-photos` forces all referenced photos to be downloaded again.

### 5.3 Removed observations: an Anki limitation

**Importing an `.apkg` never deletes notes from Anki.** Notes for removed observations will therefore stay in the user's collection. The tool must:

- leave them out of the new `.apkg`;
- list them in the report with an Anki search the user can paste, for example `"deck:iNaturalist::My observations" (obs_id:123 or obs_id:456)`;
- keep their cached photos unless `--prune` is passed.

Automatic deletion via the AnkiConnect add-on is a possible later feature. Do not build it in v1.

## 6. Rate limiting and large runs

iNat's guidance: keep to about 1 request per second and around 10k API requests per day. HTTP 429 means throttling, and IPs that persistently exceed the limits may be blocked. More than 5 GB of media per hour or 24 GB per day may result in a **permanent** block.

Implementation:

- One shared throttle for API calls **and** photo downloads, with a minimum interval of `1.0 s` by default. It is configurable down to `0.91 s` (1.1 req/s, the +10% ceiling) and never lower. Bursty usage does not justify a faster rate: the per-second limit applies within a burst.
- A daily request counter persisted in state (per UTC day). Refuse to exceed 11,000 requests (10k + 10%) without `--force`.
- A bandwidth counter. Pause if the rolling hour would exceed 4.5 GB, a safety margin under the 5 GB permanent-block threshold. **Do not apply the +10% tolerance to media limits**, because the penalty is a permanent block.
- On 429 or 5xx: retry with exponential backoff (2, 4, 8, 16, 32 s, then fail), honouring `Retry-After` if present.
- Use a session (`requests.Session`) for connection reuse.

Large-run handling (R8):

- Before downloading, print: the number of photos, the estimated size (assume 250 KB per `large` photo and 80 KB per `medium` until real sizes are known from the cache), and the estimated time at the configured rate.
- If downloads exceed `--warn-threshold` (default 200 photos), prompt `Continue? [y/N]`. `--yes` skips the prompt; `--max-downloads N` caps the run, and the remainder is picked up next run.
- Write each photo atomically (to a temporary file, then rename) and update state after each photo, so Ctrl-C loses at most one download.
- Building the deck from a partial cache is allowed. Observations whose front photo is missing are deferred to the next run and listed in the report.

## 7. Note type and card design

### 7.1 Stable identifiers

- Model ID and deck ID: random constants generated **once** and hard-coded, in the range `[1 << 30, 1 << 31)` as genanki recommends. Never change them.
- Note GUID: `genanki.guid_for("inat-obs", obs_id)`. This makes re-imports update notes instead of duplicating them.
- Deck name: `iNaturalist::My observations`. The `::` nesting leaves room for future location decks.
- Media filenames: `inat_<photo_id>.<ext>`. Anki's media folder is flat, and iNat URLs all end in names like `large.jpg`.

### 7.2 Fields

**Fix the field list now and keep it.** Changing a note type's fields later forces Anki to treat the import as a schema change, which is disruptive. Include fields needed by planned features even if v1 leaves some empty.

| Field | Content |
|-------|---------|
| `ObsID` | Observation ID (sort field) |
| `FrontPhoto` | `<img src="inat_<id>.jpg">` |
| `ExtraPhotos` | Other photos of the observation, as `<img>` tags |
| `CommonName` | UK English common name; empty if none |
| `ScientificName` | Scientific name, unformatted (the template adds the italics) |
| `Rank` | Taxon rank; shown only if not `species` (research grade can be genus level) |
| `ObservedOn` | British format, e.g. `Sat 4 May 2024, 14:32`, in the observation's local time; date only if no time |
| `Place` | `place_guess`, with `(location obscured)` appended if obscured |
| `Coordinates` | `lat, lon (±accuracy m)`; empty if obscured or missing |
| `ObsURL` | `https://www.inaturalist.org/observations/<id>` |
| `TaxonID` | iNat taxon ID |
| `Source` | `user:<login>` in v1; `place:<id>` for future location decks |
| `PhotoCredits` | One line per photo: attribution plus licence label |

Tags: `inat::iconic::<iconic_taxon_name>`, `inat::order::<name>`, `inat::family::<name>` (from `taxon.ancestors` if present, otherwise one extra batched `/v1/taxa?id=…` call per 30 taxa, cached), and `inat::user::<login>`.

### 7.3 Templates

Templates live in `templates/front.html`, `templates/back.html` and `templates/style.css`, loaded at build time. They must work unchanged in genanki-js later.

- **Front:** `{{FrontPhoto}}` only, scaled to fit the screen (`max-width: 100%; max-height: 70vh`).
- **Back:** `{{FrontSide}}`, a rule, then:
  - `CommonName` as a heading. If it is empty, show the scientific name in its place.
  - `ScientificName` in italics below it, plus `Rank` in brackets if present.
  - `ObservedOn` and `Place`, then `Coordinates` in smaller text.
  - `ExtraPhotos` as a responsive grid.
  - `PhotoCredits` in small text, and a link to `ObsURL`.
- Support Anki's night mode (`.nightMode` class) and phone widths.

### 7.4 Open design questions (defaults chosen; the user may override)

1. **Which photo goes on the front?** Default: the observation's first photo, which is the observer's chosen lead photo. Alternative: a random photo per review via JavaScript, which works in Anki but is harder to test.
2. **Photo size.** Default: `large` (1024 px on the long edge). The deck is studied on a phone with a high-density screen, where a full-width image spans roughly 1100 to 1300 physical pixels. `medium` (500 px) would be upscaled about 2.5×, which is visibly soft for fine identification features. The cost of `large` is bytes, not requests, and at this scale it is well within the bandwidth limits. `medium` remains a supported option. Changing the size later re-downloads the affected photos, so store the size in state and treat a mismatch as "needs download".
3. **Deck output.** Default: every run writes the full deck, which is robust and idempotent. `--changed-only` writes just the new and changed notes, giving smaller imports.

## 8. Licensing (R10)

- **Code:** MIT `LICENSE` file at the root, with the user's name and the year 2026.
- **Photos in v1:** the user's own photos. The user holds the copyright whatever the licence, so all of them may be used. The credits line (`photos[].attribution` plus licence) is still shown on every card.
- **Photos in future location decks (other people's photos):** implement the policy now in `licensing.py` as a pure function `is_usable(photo, observer_login, user_login) -> bool`, with tests:
  - always allowed if the observer is the user;
  - allowed: `cc0`, `cc-by`, `cc-by-sa`, `cc-by-nc`, `cc-by-nc-sa`, `cc-by-nd`, `cc-by-nc-nd`, for **personal, non-commercial** use, with attribution shown on the card. Including a resized photo unchanged on a card is reproduction, not adaptation, so ND is acceptable;
  - excluded: `null` (all rights reserved) and anything unrecognised;
  - the README must state that sharing a generated deck publicly brings in NC and SA obligations, and that commercial use is not permitted for NC photos.
- **Observation data:** show the iNat link on every card. The README credits iNaturalist as the data source.

## 9. CLI

```
inat-anki sync --user <login>
    [--out iNaturalist.apkg]       default ./iNaturalist.apkg
    [--cache-dir ./inat-cache]
    [--photo-size large|medium]
    [--refresh-photos]             re-download all referenced photos
    [--changed-only]               apkg with only new/changed notes
    [--prune]                      delete cached photos no longer referenced
    [--warn-threshold 200] [--max-downloads N] [--yes]
    [--rate 1.0]                   requests/second, max 1.1
    [--dry-run]                    fetch metadata and print the plan; no downloads, no deck
    [--verbose]
```

Settings may also come from `inat-anki.toml`. Command-line flags override the file.

**Run report** (printed and saved to `cache/last-run.json`): observations fetched; new, changed, unchanged and removed counts; photos downloaded and bytes; observations skipped and why; removed observations with their Anki search string; API requests used today.

## 10. Designing for future requirements

- **Sources.** Define a `Source` protocol with `fetch() -> list[Observation]` and a `source_key`. v1 implements `UserObservationsSource`. A future `PlaceSource` (place ID, or lat/lng/radius) would use `/v1/observations/species_counts` and select CC-licensed representative photos via `licensing.is_usable`.
- **GUID namespacing.** User cards use `("inat-obs", obs_id)`. Future location cards would use `("inat-place", place_key, taxon_id)`, so the two never collide.
- **Taxon filtering.** Add a `--taxon-id` parameter, passed to the API as `taxon_id`, and nest output decks as `iNaturalist::My observations::Birds`. The tags already support filtered decks in Anki.

## 11. Portability to the web app

The later web app will be a **Svelte 5 + TypeScript** single-page app, built with Vite (or SvelteKit with `adapter-static` and SSR disabled, so it stays fully client-side). It will run in the browser using genanki-js (sql.js + JSZip). Do not build any of it in v1. To keep the port mechanical:

- Keep **pure modules** with no I/O: `model.py`, `normalise.py`, `plan.py`, `render.py`, `licensing.py`. These hold all the logic and are translated one-to-one into TypeScript.
- Keep **I/O modules** thin: `api.py` (HTTP, throttle), `media.py` (photo cache), `state.py` (JSON file), `deck.py` (genanki). In the browser, these become `fetch`, IndexedDB and genanki-js.
- The `state.json` schema is versioned (`"schema_version": 1`) and documented in `docs/state-schema.md`. The web app will store the same structure in IndexedDB.
- Templates and CSS are plain files shared verbatim.
- Model ID, deck ID and GUID scheme are documented in `docs/anki-identity.md`. **The web app must reuse them** so that decks from either tool update the same notes.
- Known web-app risk to record in the docs: browser `fetch` of photos needs CORS headers on both photo hosts. This is unverified. If CORS is absent, the fallback is hotlinked `<img src>` (no CORS needed, but cards need a connection).

## 12. Repository layout

```
inat-anki/
  LICENSE                 MIT
  README.md               install, usage, Anki import steps, licensing notes, credits
  pyproject.toml
  uv.lock
  .python-version
  inat-anki.example.toml
  docs/
    api-notes.md          findings from section 2
    state-schema.md
    anki-identity.md
  templates/
    front.html  back.html  style.css
  src/inat_anki/
    __init__.py  cli.py
    api.py  throttle.py  media.py  state.py  deck.py      (I/O)
    model.py  normalise.py  plan.py  render.py  licensing.py   (pure)
    sources.py
  tests/
    fixtures/             recorded API JSON (anonymise usernames if committing)
    test_normalise.py  test_plan.py  test_render.py
    test_licensing.py  test_throttle.py  test_deck.py
```

## 13. Testing and acceptance

Tests must not hit the network. Use recorded fixtures, and inject a fake clock into the throttle.

Required test cases:

- Paging with `id_above` across more than 200 results.
- Plan: new, changed (taxon change), removed (lost research grade), unchanged; a missing photo file; a sha256 mismatch.
- Render: no common name; genus-level research grade; obscured location; no time; British date format; HTML-escaping of user-entered `place_guess`.
- Licensing: every licence code, `null`, unknown values, owner override.
- Throttle: never faster than the configured rate; refuses a rate above 1.1/s; backoff on 429 honours `Retry-After`.
- Deck: GUIDs are stable across builds; model and deck IDs are constant; media filenames are unique; the `.apkg` opens (unzip it and query the `notes` table with sqlite3).

Acceptance (manual, with the real account):

1. First run on 154 observations finishes with no 429s, and the deck imports into Anki with one card per research-grade observation that has photos.
2. An immediate second run downloads **zero** photos, makes 1 API request, and re-importing produces no duplicates.
3. After a new observation becomes research grade, the next run downloads only its photos, and import adds exactly one card. Review history on existing cards is unchanged.
4. Cards display correctly on Anki desktop and AnkiDroid or AnkiMobile, in light and night mode.

## 14. Out of scope for v1

Location decks; taxon filtering; AnkiConnect integration; authenticated API access (needed only for unobscured private coordinates); the web app; sound cards.
