# inat-anki

Turn your research-grade [iNaturalist](https://www.inaturalist.org) observations into an
Anki deck, so you can learn to recognise the species you have seen yourself.

Each observation becomes one card. The front shows your photo. The back shows the common
name (UK English), the scientific name, and when and where you saw it, followed by any
other photos and a link back to the observation.

Re-running it is cheap and safe. It downloads only photos it hasn't already cached, and
re-importing the deck updates your existing cards without duplicating them or losing
their review history.

## Install

You need [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/Tom271/inat-anki.git
cd inat-anki
uv tool install .        # puts `inat-anki` on your PATH
```

Or run it from the checkout without installing: `uv run inat-anki ...`.

## Usage

```sh
inat-anki sync --user <your-inat-login>
```

This writes `iNaturalist-<login>-<YYYY-MM-DD>.apkg` in the current directory, and keeps
its photo cache and state in `./inat-cache/`. Keep that directory: it's what makes later
runs incremental.

Useful options:

| Option | Effect |
|---|---|
| `--dry-run` | Fetch the observation list and print the plan, then stop. No downloads, no deck. |
| `--out FILE` | Write the deck to `FILE` instead of the dated default name. |
| `--photo-size medium` | Use ~500 px photos instead of ~1024 px (`large`, the default). |
| `--changed-only` | Put only new and changed notes in the `.apkg`, giving a smaller import. |
| `--max-downloads N` | Download at most N photos now; the rest are fetched on later runs. |
| `--yes` | Don't ask for confirmation before large downloads (more than 200 photos by default; see `--warn-threshold`). |
| `--refresh-photos` | Download every photo again. |
| `--prune` | Delete cached photos that no deck uses any more. |
| `--rate R` | Requests per second, at most 1.1 (default 1.0). |
| `--verbose` | Show each photo as it downloads. |

Run `inat-anki sync --help` for the full list.

### Config file

Settings can also live in `inat-anki.toml` in the current directory, or in the file given
with `--config`. Flags override the file. Copy
[`inat-anki.example.toml`](inat-anki.example.toml) to start.

## Common UK species decks (shareable)

```sh
inat-anki species
```

This builds `iNaturalist-UK-common-<YYYY-MM-DD>.apkg`, with a subdeck per group under
**iNaturalist::UK common species**, about 425 cards in all. The groups are:

- birds, mammals, and reptiles and amphibians;
- insects and seashore life;
- trees, plants and grasses;
- mosses, liverworts, fungi and lichens;
- the commonest farm breeds.

Species are ranked by UK research-grade observations on iNaturalist. Each card has two
photos, and **every photo is CC0, CC BY or CC BY-SA**, so the deck can be shared. Each card
credits its photographers, with links to the licence and the source. Farm breed photos
come from Wikimedia Commons.

- **Your sightings:** species you have observed are tagged `inat::seen`. Set `seen_by`
  in the sets file, or pass `--seen-by ""` when building a deck to share.
- **Run time:** the first run makes about 1,300 requests (20 to 30 minutes, at 1 request
  per second) and asks before downloading. Later runs make a few dozen requests.
- **Sticky groups:** groups only grow. Use `--rerank` to rebuild them from the current
  ranking.
- **Breed photos:** run `inat-anki species --suggest-breed-photos` to get a page of
  licence-checked Commons candidates for each breed. Copy your picks into the breed's
  `photos` list in `src/inat_anki/data/lists/uk-farm-breeds.toml`.
- **Customising:** the sets are defined in
  [`src/inat_anki/data/uk-common.toml`](src/inat_anki/data/uk-common.toml). Copy it and
  pass it with `--sets` to build your own groups.

## Importing into Anki

1. In Anki desktop, choose **File → Import…** and pick the `.apkg`.
2. The cards appear in the deck **iNaturalist::My observations**.
3. Sync to AnkiWeb to get them on AnkiDroid or AnkiMobile.

To update the deck later, run `inat-anki sync` again and import the new file. New
observations, and observations that have since reached research grade, are added. Cards
whose identification or details changed are updated in place.

### Observations that disappear

If an observation is deleted, or is no longer research grade, it's left out of the next
deck. But **importing can't delete cards from Anki**, so its card stays in your
collection. The run report lists these observations, with a search you can paste into
Anki's browser to find and delete them, for example:

```
"deck:iNaturalist::My observations" (ObsID:123 or ObsID:456)
```

The report is printed at the end of each run and saved to `inat-cache/last-run.json`.

### Filtered decks

Every card is tagged with its taxonomy, for example `inat::iconic::Aves`,
`inat::order::Lepidoptera` and `inat::family::Araneidae`. To study one group, create a
filtered deck in Anki with a search such as `tag:inat::iconic::Plantae`.

## Being kind to iNaturalist

The tool stays within iNaturalist's published limits:

- at most 1 request per second, adjustable up to 1.1 per second;
- at most 11,000 requests per UTC day, unless you pass `--force`;
- under 4.5 GB of photos per hour, a margin below the 5 GB at which iNat may block a
  client permanently.

It identifies itself with a `User-Agent` that includes your login. When throttled (HTTP
429) or when iNat has server errors, it waits with exponential backoff before retrying.
Before a large run it shows the estimated size and time and asks you to confirm. If a run
is interrupted, it resumes where it stopped.

## Licensing

**Code:** MIT, see [LICENSE](LICENSE).

**Photos:** the deck contains only **your own** photos. You hold their copyright whatever
licence you chose on iNaturalist, so you can use them as you like. Every card still shows
each photo's attribution and licence.

Future decks built from **other people's** photos (see
[`licensing.py`](src/inat_anki/licensing.py)) will only use Creative Commons-licensed
photos, never "all rights reserved" ones, and will credit each photographer on the card.
If you share such a deck publicly:

- **NC** (non-commercial) photos may not be used commercially, so a deck containing them
  can't be sold or used for commercial purposes;
- **SA** (share-alike) photos keep their licence, and adaptations of them must be shared
  under the same licence;
- attribution must stay on the cards.

**Data:** the observation data and photos come from
[iNaturalist](https://www.inaturalist.org). Every card links back to its observation.
This project isn't affiliated with or endorsed by iNaturalist.

## Development

```sh
uv sync
uv run pytest        # tests never touch the network
uv run ruff check
```

- **Layout:** logic with no I/O lives in `model.py`, `normalise.py`, `plan.py`,
  `render.py` and `licensing.py`. The thin I/O modules are `api.py`, `throttle.py`,
  `media.py`, `state.py` and `deck.py`. This split is so that a future browser version can
  port the logic one-to-one.
- **Further docs:**
  - [`docs/api-notes.md`](docs/api-notes.md): what the live iNaturalist API actually
    returns.
  - [`docs/state-schema.md`](docs/state-schema.md): the cache's `state.json`.
  - [`docs/anki-identity.md`](docs/anki-identity.md): the Anki IDs and GUID scheme. These
    must never change.
- **Test fixtures:** the scripts in `scripts/` re-check the live API and rebuild the
  anonymised fixtures in `tests/fixtures/`.
