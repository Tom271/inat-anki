# inat-anki v2: shareable decks of common UK species

This builds on v1 (`SPEC.md`). Everything in v1 stays as it is, including the
`iNaturalist::My observations` deck, its IDs and its state.

## 1. Purpose

Generate one combined, **shareable** Anki deck of the most commonly observed species in
the UK, in separate subdecks for each group. The point is to learn local wildlife,
including species you haven't seen yet. Each **species** gets one card, rather than each
observation. The front shows photos taken by iNaturalist users; the back shows the
identification.

Every photo must be licensed so that the deck can be **shared publicly**, for example on
AnkiWeb, with attribution on each card.

## 2. Decisions already made

| Decision | Choice |
|---|---|
| Licence policy | **Shareable**: `cc0`, `cc-by` and `cc-by-sa` only. No NC, no ND, and never "all rights reserved". |
| Rocks and geology | **Out of scope.** Not built, and not designed for. |
| Card unit | One note per species. |
| Ranking | Number of UK research-grade, wild (not captive) observations, from iNat. |

## 3. Facts checked against the live API (2026-10-10)

These came from `scripts/verify_v2.py`; details are in `docs/api-notes.md`, section 8.

| Taxon | iNat ID | Rank |
|---|---|---|
| Aves (birds) | 3 | class |
| Fungi (iNat's name: "Fungi Including Lichens") | 47170 | kingdom |
| Lecanoromycetes ("Common Lichens") | 54743 | class |
| Bryophyta (mosses) | 311249 | phylum |
| Marchantiophyta (liverworts) | 64615 | phylum |
| Plantae | 47126 | kingdom |
| Polypodiopsida (ferns) | 121943 | class |
| Pinopsida (conifers) | 136329 | class |
| Magnoliopsida (dicots) | 47124 | class |
| Reptilia | 26036 | class |
| Amphibia | 20978 | class |
| Mammalia | 40151 | class |

- `GET /v1/observations/species_counts`, with `place_id=6857`, `quality_grade=research`,
  `captive=false` and `rank=species`, returns species ranked by observation count. The
  top UK birds are European Robin (43,195), Mallard and Common Wood-Pigeon. There are
  598 bird species in total.
- `without_taxon_id` works on `species_counts`. Fungi without Lecanoromycetes gives Fly
  Agaric, Jelly Ear, Birch Polypore and so on. Lecanoromycetes alone gives Xanthoria
  parietina, Evernia prunastri and Parmelia sulcata, so it's a good definition of "common
  lichens".
- **The species' default photo can't be relied on.** Of the top 10 birds, the Robin's
  and Mute Swan's are "all rights reserved", and three more are NC. Photos therefore come
  from licence-filtered observations (section 6).
- `photo_license=cc0,cc-by,cc-by-sa` on `/v1/observations` works: there are 2,021 UK
  research-grade Robin observations with such photos. They're served from
  `inaturalist-open-data.s3.amazonaws.com`, which sends `Access-Control-Allow-Origin: *`,
  so the web app could fetch them.
- A list of IDs in `taxon_id` matches the **descendants** of each taxon too. A
  hand-picked species list must therefore be filtered on our side, keeping only the
  listed IDs.
- `order_by=votes` makes little difference: most observations have 0 or 1 votes.

Still unverified, and to be checked before building, as in v1 section 2:

- IDs for algae within Plantae: Rhodophyta and Chlorophyta. These are to be excluded
  from the plants set.
- Whether hornworts (Anthocerotophyta) appear in UK results.
- Whether `species_counts` can return more than 500 results per page.

## 4. Sets

A **set** is one subdeck. The set definitions are data, not code, and are shipped as
`sets/uk-common.toml`:

| Set | Count | Definition |
|---|---|---|
| Birds | 50 | `taxon_id = 3` |
| Fungi | 50 | `taxon_id = 47170`, `without_taxon_id = 54743`, and exclude any species in the Lichens set |
| Lichens | 10 | `taxon_id = 54743` |
| Mosses | 10 | `taxon_id = 311249` |
| Trees | 50 | Hand-picked species list `lists/uk-trees.txt`, ranked by `species_counts` |
| Plants (non-trees) | 100 | `taxon_id = 47126`, `without_taxon_id = 311249,64615,<algae>`, and exclude the Trees list |
| Reptiles and amphibians | 20 | `taxon_id = 26036,20978` |
| Mammals | 10 | `taxon_id = 40151` |

This is 300 species in total. The format looks like this:

```toml
place_id = 6857
deck = "iNaturalist::UK common species"
photos_per_species = 4

[[set]]
key = "birds"                # stable: used in deck IDs and state; never rename
name = "Birds"
taxon_id = [3]
count = 50

[[set]]
key = "fungi"
name = "Fungi"
taxon_id = [47170]
without_taxon_id = [54743]
exclude_sets = ["lichens"]
count = 50

[[set]]
key = "trees"
name = "Trees"
species_list = "lists/uk-trees.txt"   # scientific names, one per line
count = 50
```

Rules:

- **No duplicates across sets.** A species appears in at most one set. `exclude_sets`
  makes the overlaps explicit (trees inside plants, lichens inside fungi). The build fails
  if any overlap remains.
- **Ranking:** `species_counts` returns `count` plus a buffer, because species without a
  usable photo are skipped (section 6) and the next species moves up.
- **Species lists:** names are resolved to taxon IDs once, with `/v1/taxa?q=`, and the
  result is cached in state. Unresolved or ambiguous names fail the build and are listed.
  Ranking uses `species_counts` with every listed ID, then **keeps only the listed IDs**,
  because of the descendants behaviour in section 3.
- **Adding a set is a config change, not a code change.** Butterflies, dragonflies, ferns
  and so on can be added later this way.

### 4.1 Set membership over time

Rankings drift as people observe more. **Membership is sticky by default.** Once a
species has entered a set, it stays in that set's deck, even if it later drops out of the
top N. This is because Anki can't delete notes on import (v1 section 5.3), and churning
cards is bad for learning. Newcomers to the top N are added. The report lists species
that have dropped below the cut-off. `--rerank` rebuilds membership from scratch, and
reports the species that left, with an Anki search, as v1 does.

## 5. Note type, decks and identity

This is a **new note type**. The v1 note type's date, place and coordinates fields
describe a single observation and don't fit a species card.

| Field | Content |
|---|---|
| `TaxonID` | Sort field. |
| `FrontPhoto` | `<img>` of the first chosen photo. |
| `ExtraPhotos` | The other chosen photos, as `<img>` tags. |
| `CommonName` | UK English, as in v1. |
| `ScientificName` | Unformatted; the template adds italics. |
| `Rank` | Shown only if not `species`. |
| `Group` | The set name, for example "Birds". |
| `Family` | From the cached ancestry, as in v1. |
| `Order` | As above. |
| `UKObservations` | The research-grade UK count when the card was built, for example "43,195 UK observations". |
| `TaxonURL` | `https://www.inaturalist.org/taxa/<id>` |
| `PhotoCredits` | One line per photo: attribution, licence **linked to its licence deed**, and a link to the source observation. |
| `Source` | `place:6857:<set key>` |

Fix this field list now, as in v1 section 7.2.

| Identity | Value |
|---|---|
| Model ID | A new random constant in `[1 << 30, 1 << 31)`, hard-coded and documented in `docs/anki-identity.md` |
| Model name | `iNaturalist species` |
| Note GUID | `genanki.guid_for("inat-place", place_key, taxon_id)`, where `place_key = "6857"`, as v1 section 10 planned. It's independent of the set, so a species keeps its review history if it moves between sets. |
| Deck name | `iNaturalist::UK common species::<set name>` |
| Deck ID | Derived from the set **key**, because sets are config-defined: the first 8 bytes of `sha256("inat-anki-deck:" + key)` mapped into `[1 << 30, 1 << 31)`. Documented and pinned in tests. |
| Media filenames | `inat_<photo_id>.<ext>`, as in v1 |

The templates sit in `src/inat_anki/templates/species/`, with the same layout and
night-mode rules as v1. The front shows `FrontPhoto` only; the back shows the
identification, family and order, the extra-photo grid and the credits.

**Optional extra:** if the v1 state for `--user` is available, tag species you have
observed yourself with `inat::seen`. Then a filtered deck can show only species you
haven't seen yet. This is off by default.

## 6. Photo selection and licensing

For each species:

```
GET /v1/observations?taxon_id=<id>&place_id=6857&quality_grade=research
    &photo_license=cc0,cc-by,cc-by-sa&order_by=votes&per_page=30
```

1. Every photo still passes `licensing.is_usable(photo, observer_login, user_login,
   policy="shareable")`. The `photo_license` filter is a pre-filter, not the guarantee.
   Photos are checked one at a time, because one observation can mix licences.
2. Choose up to `photos_per_species` photos (default 4), **each from a different
   observation, and preferably from different observers**, so the card shows variety. The
   first is the front photo.
3. If fewer than one usable photo is found in the UK, retry without `place_id`. If there's
   still none, skip the species and list it in the report.
4. **Choices are sticky.** Chosen photo IDs are stored in state and reused on later runs,
   so cards don't change on every rebuild. A photo is replaced only if its observation
   disappears, it loses research grade, or its licence changes to one that isn't usable.
   `--reselect-photos` forces a fresh choice.
5. The licence is re-checked against the API on every run, because users can change
   licences.

`licensing.py` gains a policy parameter:

| Policy | Accepts | Used by |
|---|---|---|
| `personal` | cc0, cc-by, cc-by-sa, cc-by-nc, cc-by-nc-sa, cc-by-nd, cc-by-nc-nd | v1's planned location decks, for personal study |
| `shareable` | cc0, cc-by, cc-by-sa | v2 common-species decks |

The owner override (the user's own photos) applies under both policies.

**Attribution** follows the CC "TASL" convention: title, author, source and licence. It
appears on every card, and covers the photographer (from iNat's attribution string), the
licence name **with a link to the licence deed**, and a link to the source observation.
Photos are included as iNat serves them, at `large` size, with no edits by us.

**Deck description.** genanki's `Deck(description=…)` is shown in Anki when the deck is
opened. It states:

- that the photos are by iNaturalist users, under CC0, CC BY or CC BY-SA, as credited
  on each card;
- that CC BY-SA photos remain under CC BY-SA;
- that the data comes from iNaturalist.

## 7. CLI

```
inat-anki species
    [--sets sets/uk-common.toml]
    [--out ./iNaturalist-UK-common-<YYYY-MM-DD>.apkg]
    [--cache-dir ./inat-cache-species]
    [--only birds,mammals]      build just these sets (other subdecks are left out of the .apkg)
    [--rerank] [--reselect-photos]
    [--seen-by <login>]         tag species this user has observed (optional extra)
    [--photo-size large|medium] [--warn-threshold] [--max-downloads] [--yes]
    [--rate] [--dry-run] [--prune] [--force] [--verbose]
```

The cache is separate from v1's. Its `source_key` is `place:6857:uk-common`, which v1's
one-source-per-cache rule needs. State is a new schema with its own `schema_version`,
documented in `docs/state-schema-species.md`. It holds:

- set membership (sticky);
- the resolved names from species lists;
- the photos chosen for each species, with their observation IDs and licences;
- the note hash for each species;
- the same photo records, request counter and bandwidth window as v1.

The run report is v1's, plus: species per set, species skipped for lack of photos,
species that dropped below the cut-off (sticky membership), and the licence breakdown of
the photos included.

## 8. Request and bandwidth budget

| Step | First run | Later runs |
|---|---|---|
| `species_counts`, one per set | about 8 | about 8 |
| Resolving species-list names | about 50 to 100 | 0 (cached) |
| Taxon ancestry, 30 per request | about 10 | 0 |
| Photo search, one per species | 300 | new species only, plus licence re-checks (see below) |
| Photo downloads (300 × 4) | about 1,200 | new or replaced photos only |
| **Total** | **about 1,600 requests, about 27 min** | **tens of requests** |

CC photos on the S3 host were about 212 KB at `large` in the v1 sample, so the first run
is about 250 to 800 MB. That's far under the 4.5 GB per hour limit. The first run goes
over the 200-photo warning threshold and asks for confirmation, and it can be resumed
(v1 section 6).

**Licence re-checks:** to avoid 300 requests per run, re-fetch the chosen observations in
batches. `/v1/observations?id=<id1,id2,…>` takes up to 200 IDs, which gives about 6
requests. Verify that before building.

## 9. Code structure

The v1 split between modules with no I/O and thin I/O modules is unchanged:

- **`sets.py`** (no I/O): parse and validate set config, resolve overlaps and exclusions,
  and apply sticky membership.
- **`selection.py`** (no I/O): rank candidates, filter by licence policy, choose photos
  for variety, and keep earlier choices.
- **`render_species.py`** (no I/O): species → note fields, tags and hash.
- **`sources.py`:** adds `PlaceSpeciesSource` (`species_counts` and photo search). It
  stays behind the existing `Source` protocol where that fits.
- **`deck.py`:** gains the species model, derived deck IDs, the deck description and
  multi-deck packages. genanki's `Package` accepts a list of decks.
- **`cli.py`:** adds the `species` subcommand, and shares the throttle, client, media
  cache and report code with `sync`.

## 10. Testing

As in v1, tests never touch the network: they use recorded fixtures and a fake clock.
Add fixtures for `species_counts`, licence-filtered observations (including one that
mixes licences), and taxon name lookups.

Required cases:

- **Licensing:** each policy against every licence code; shareable rejects all NC and ND
  codes and `null`; the owner override.
- **Sets:**
  - an overlap fails the build;
  - `exclude_sets` removes species;
  - an unknown key fails, as does a duplicate key;
  - descendants returned for a species list are filtered out.
- **Sticky membership:** a species below the cut-off stays; `--rerank` removes it and
  reports it.
- **Photo selection:**
  - variety across observations and observers;
  - a mixed-licence observation keeps only the usable photos;
  - falling back to photos from outside the UK;
  - skipping a species that has no usable photo;
  - sticky choices, and replacement when a licence changes.
- **Identity:**
  - deck IDs are derived deterministically and pinned in tests;
  - the species GUID is the same whichever set the species is in;
  - the model ID is constant.
- **Package:** the `.apkg` has one deck per set, with the right names; notes have the
  right model; the deck description is present; there are no duplicate GUIDs.

Acceptance, done manually:

1. The first run builds 300 cards in 8 subdecks, every photo is CC0, CC BY or CC BY-SA,
   and every card shows credits with licence links.
2. An immediate second run downloads no photos and makes 20 or fewer requests.
3. Importing on top of the v1 deck leaves `iNaturalist::My observations` untouched.
4. Cards display correctly on desktop and mobile, in light and night mode.

## 11. Out of scope

- Rocks, minerals and geology of any kind.
- Places other than the UK. The design takes `place_id` as a parameter, but only 6857 is
  tested.
- Publishing to AnkiWeb automatically, and AnkiConnect.
- Sound cards, and the web app.

## 12. Open questions for the user

1. **Trees list:** which source? The proposal is the Woodland Trust's British native trees
   plus common naturalised species (sycamore, horse chestnut, sweet chestnut and so on).
   Should commonly planted non-natives count, given that `captive=false` excludes
   observations marked as cultivated?
2. **Ferns:** part of "Plants (non-trees)", or a separate set?
3. **Photos per species:** is 4 right? More photos mean more variety but a bigger deck.
4. **Mammals:** should domestic and feral species (feral cat, feral goat) be excluded?
5. **The `inat::seen` tag:** wanted?
6. **More sets:** butterflies, dragonflies and damselflies, bees, hoverflies, ladybirds,
   spiders, ferns, liverworts, seashore life, slime moulds and galls were suggested
   earlier. Should any of them ship in `uk-common.toml`?
