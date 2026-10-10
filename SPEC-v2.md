# inat-anki v2: shareable decks of common UK species

This builds on v1 (`SPEC.md`). Everything in v1 stays as it is, including the
`iNaturalist::My observations` deck, its IDs and its state.

## 1. Purpose

Generate one combined, **shareable** Anki deck of the most commonly observed species in
the UK, in separate subdecks for each group. The point is to learn local wildlife,
including species you haven't seen yet. Each **species** gets one card, rather than each
observation. The front shows photos taken by iNaturalist users; the back shows the
identification. Species the user has already observed are tagged, so they can study
unseen species separately.

Every photo must be licensed so that the deck can be **shared publicly**, for example on
AnkiWeb, with attribution on each card.

## 2. Decisions made

| Decision | Choice |
|---|---|
| Licence policy | **Shareable**: `cc0`, `cc-by` and `cc-by-sa` only. No NC, no ND, and never "all rights reserved". |
| Rocks and geology | **Out of scope.** Not built, and not designed for. |
| Card unit | One note per species. |
| Photos per species | **2.** |
| Ranking | UK research-grade observation count from iNat. Trees also count casual-grade observations, so that commonly planted non-natives are included (section 4.2). |
| Trees | The Woodland Trust's A–Z of British trees, **including commonly planted non-natives**. |
| Ferns | Part of "Plants". |
| Mammals | Exclude domestic species. Feral populations are included. |
| Species already observed | **Tagged `inat::seen`.** This is in scope, not optional (section 5.2). |
| Sets | The 8 originally listed, plus Insects (butterflies and all other insects, as one set), Grasses, Liverworts and Seashore. |

## 3. Facts checked against the live API (2026-10-10)

These came from `scripts/verify_v2.py` and `scripts/verify_v2_sets.py`, with raw output in
`scripts/out/`. Details are in `docs/api-notes.md`, section 8.

### 3.1 Taxon IDs

| Taxon | iNat ID | Rank | Used by |
|---|---|---|---|
| Aves | 3 | class | Birds |
| Fungi ("Fungi Including Lichens") | 47170 | kingdom | Fungi |
| Lecanoromycetes ("Common Lichens") | 54743 | class | Lichens; excluded from Fungi |
| Bryophyta (mosses) | 311249 | phylum | Mosses; excluded from Plants |
| Marchantiophyta (liverworts) | 64615 | phylum | Liverworts; excluded from Plants |
| Anthocerotophyta (hornworts) | 56327 | phylum | Excluded from Plants. Only 4 UK research-grade observations, so no set. |
| Plantae | 47126 | kingdom | Plants |
| Poaceae (grasses) | 47434 | family | Grasses; excluded from Plants |
| Rhodophyta (red algae) | 57774 | phylum | Seashore; excluded from Plants (iNat puts it in Plantae) |
| Chlorophyta (green algae) | 50863 | phylum | Excluded from Plants |
| Ulvophyceae (green seaweeds) | 51429 | class | Seashore |
| Phaeophyceae (brown seaweeds) | 48220 | class | Seashore (iNat puts it in Chromista, not Plantae) |
| Echinodermata | 47549 | phylum | Seashore |
| Cnidaria | 47534 | phylum | Seashore |
| Cirripedia (barnacles) | 210289 | infraclass | Seashore |
| Brachyura (true crabs) | 121639 | infraorder | Seashore |
| Polyplacophora (chitons) | 47429 | class | Seashore |
| Littorinidae, Patellidae, Mytilidae, Cardiidae, Trochidae, Muricidae (periwinkles, limpets, mussels, cockles, topshells, dogwhelks) | 48918, 51740, 50600, 50597, 53830, 50766 | family | Seashore |
| Insecta | 47158 | class | Insects |
| Reptilia | 26036 | class | Reptiles and amphibians |
| Amphibia | 20978 | class | Reptiles and amphibians |
| Mammalia | 40151 | class | Mammals |
| *Homo sapiens*, *Canis familiaris*, *Felis catus*, *Bos taurus*, *Ovis aries*, *Sus scrofa domesticus* | 43584, 47144, 118552, 74113, 121578, 324492 | species or subspecies | Excluded from Mammals |

### 3.2 Behaviour

- **Ranking.** `GET /v1/observations/species_counts` with `place_id=6857`,
  `quality_grade=research` and `rank=species` ranks species by count. `per_page=500` works.
  `without_taxon_id` works, and also excludes descendants.
- **Research grade already excludes captive and cultivated observations.** The results
  were identical with and without `captive=false`. Domestic mammals don't appear in the
  top 15 UK mammals for this reason. The explicit exclusion list in section 4 is a safety
  net. Feral animals that aren't marked captive, such as feral goats and semi-feral
  ponies, come through naturally.
- **Planted trees are cultivated, so they're never research grade.** Counting
  `quality_grade=research,casual` brings monkey puzzle, Japanese cherry, Lawson cypress,
  box and common lime into the top 50 trees. It pushes out downy birch, alder buckthorn,
  crab apple, black poplar and small-leaved lime.
- **"Complex" taxa share species' names.** For example, iNat has both *Quercus robur* the
  species (56133) and a *Quercus robur* **complex** (1520309), and the complex has more
  observations because it includes the species. This applies to oaks, sycamore, hawthorns,
  elder, guelder rose and field elm. **Name resolution must prefer rank `species` or
  `hybrid`.**
- **Hybrids have rank `hybrid`.** London plane, common lime, crack willow and Huntingdon
  elm are hybrids, and `rank=species` drops them. Hand-picked lists must rank with
  `rank=species,hybrid`.
- **Renamed species.** iNat uses newer names for some trees: whitebeam is *Aria edulis*,
  wild service tree is *Torminalis glaberrima*, Leyland cypress is
  *× Hesperotropsis leylandii*, and Arran whitebeam is *Hedlundia arranensis*. The tree
  list stores taxon IDs, so later renames don't matter.
- **A list in `taxon_id` matches descendants.** Filter results down to the listed IDs.
- **Default photos can't be relied on.** Of the top 10 UK birds, 2 have "all rights
  reserved" default photos (Robin and Mute Swan) and 3 have NC ones. Photos come from
  licence-filtered observations instead (section 6).
- **The licence filter works.** `photo_license=cc0,cc-by,cc-by-sa` on `/v1/observations`
  finds 2,021 UK research-grade Robin observations. Their photos are served from
  `inaturalist-open-data.s3.amazonaws.com`, which sends CORS headers.
- **Batch lookup works.** `/v1/observations?id=<71 ids>` returned all 71.
- **Votes don't help.** `order_by=votes` makes little difference: most observations have 0
  or 1 votes.

### 3.3 Previews: the current top species in each set

| Set | Top species |
|---|---|
| Birds | European Robin (43,195 observations), Mallard, Common Wood-Pigeon, Eurasian Blackbird, Mute Swan |
| Trees (including casual) | Elder (23,605), Sycamore, Hawthorn, Holly, Hazel |
| Plants (after the exclusions) | Herb Robert (32,266), Red Campion, Common Nettle, Lesser Celandine, Daisy |
| Grasses | Cock's-foot (8,759), Yorkshire Fog, Common Reed, Meadow Foxtail, Wall Barley |
| Insects | Harlequin Ladybird (57,746), 7-spot Ladybird, Speckled Wood, Red Admiral, Peacock |
| Liverworts | Crescent-cup Liverwort (2,261), Common Liverwort, Dilated Scalewort, Forked Veilwort |
| Seashore | Green Shore Crab (10,089), Beadlet Anemone, Snakelocks Anemone, Dogwhelk, Common Periwinkle, Edible Crab, Bladder Wrack |
| Mammals | Grey Squirrel (26,476), Hedgehog, Rabbit, Red Fox, Roe Deer |

## 4. Sets

A **set** is one subdeck. The set definitions are data, not code, and are shipped as
`sets/uk-common.toml`:

| Set | Count | Definition |
|---|---|---|
| Birds | 50 | `taxon_id = [3]` |
| Mammals | 10 | `taxon_id = [40151]`, `without_taxon_id = [43584, 47144, 118552, 74113, 121578, 324492]` |
| Reptiles and amphibians | 20 | `taxon_id = [26036, 20978]` |
| Insects | **50** (open question 1) | `taxon_id = [47158]` |
| Seashore | 20 | `taxon_id =` the 14 seashore groups in section 3.1 |
| Trees | 50 | `species_list = "lists/uk-trees.txt"`, `quality_grade = "research,casual"` |
| Plants | 100 | `taxon_id = [47126]`, `without_taxon_id = [311249, 64615, 56327, 57774, 50863, 47434]`, `exclude_sets = ["trees"]`. Ferns are included. |
| Grasses | **20** (open question 1) | `taxon_id = [47434]` |
| Mosses | 10 | `taxon_id = [311249]` |
| Liverworts | 10 | `taxon_id = [64615]` |
| Fungi | 50 | `taxon_id = [47170]`, `without_taxon_id = [54743]`, `exclude_sets = ["lichens"]` |
| Lichens | 10 | `taxon_id = [54743]` |

This is **400 species** in 12 subdecks. The format looks like this:

```toml
place_id = 6857
deck = "iNaturalist::UK common species"
photos_per_species = 2
seen_by = "tom1591"            # tag species this user has observed (section 5.2)

[[set]]
key = "mammals"                # stable: used in deck IDs and state; never rename
name = "Mammals"
taxon_id = [40151]
without_taxon_id = [43584, 47144, 118552, 74113, 121578, 324492]  # domestic species
count = 10

[[set]]
key = "trees"
name = "Trees"
species_list = "lists/uk-trees.txt"
quality_grade = "research,casual"   # count planted (cultivated) trees too
count = 50

[[set]]
key = "plants"
name = "Plants"
taxon_id = [47126]
without_taxon_id = [311249, 64615, 56327, 57774, 50863, 47434]
exclude_sets = ["trees"]
count = 100
```

The per-set options, with their defaults:

| Option | Default | Notes |
|---|---|---|
| `quality_grade` | `"research"` | |
| `rank` | `"species"` | For `species_list` sets the default is `"species,hybrid"`. |
| `without_taxon_id` | `[]` | |
| `exclude_sets` | `[]` | |

Rules:

- **No duplicates across sets.** A species appears in at most one set. `exclude_sets`
  makes the overlaps explicit (trees inside plants, lichens inside fungi). The build fails
  if any overlap remains.
- **Ranking:** `species_counts` is called with `per_page = count + buffer`, at most 500,
  because species without a usable photo are skipped (section 6) and the next species
  moves up.
- **Adding a set is a config change, not a code change.**

### 4.1 Species lists

`lists/uk-trees.txt` is committed, and is tab-separated: `taxon_id`, the iNat name, and the
entry as listed. `#` starts a comment line. It holds the 79 Woodland Trust entries mapped to
species, plus Japanese larch and Japanese cherry as common planted additions.

- Copper beech and Irish yew are cultivars of beech and yew, so they aren't separate
  entries.
- "Cedar" maps to cedar of Lebanon, and "Eucalyptus" to cider gum.

The IDs were resolved and checked once, by `scripts/verify_v2_trees_resolve.py`, so builds
make no name-lookup requests. The build checks each ID with the taxa request it makes
anyway for ancestry (section 8), and fails on any inactive or unknown ID. The list was
checked on 2026-10-10: all 79 entries resolve, and all 79 rank.

Results are ranked with `species_counts`, passing every listed ID, then **only the listed
IDs are kept**, because the list also matches descendants.

### 4.2 Set membership over time

Rankings drift as people observe more. **Membership is sticky by default.** Once a
species has entered a set, it stays in that set's deck, even if it later drops out of the
top N. This is because Anki can't delete notes on import (v1 section 5.3), and churning
cards is bad for learning. Newcomers to the top N are added. The report lists species
that have dropped below the cut-off. `--rerank` rebuilds membership from scratch, and
reports the species that left, with an Anki search, as v1 does.

## 5. Note type, decks and identity

### 5.1 Note type

This is a **new note type**. The v1 note type's date, place and coordinates fields
describe a single observation and don't fit a species card.

| Field | Content |
|---|---|
| `TaxonID` | Sort field. |
| `FrontPhoto` | `<img>` of the first chosen photo. |
| `ExtraPhotos` | The other chosen photo, as an `<img>` tag. There's room for more if `photos_per_species` is raised later. |
| `CommonName` | UK English, as in v1. |
| `ScientificName` | Unformatted; the template adds italics. |
| `Rank` | Shown only if not `species`, for example `hybrid`. |
| `Group` | The set name, for example "Birds". |
| `Family` | From the cached ancestry, as in v1. |
| `Order` | As above. |
| `UKObservations` | The UK count when the card was built, for example "43,195 UK observations". |
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
identification, family and order, the second photo and the credits. Cards for seen
species show a small "Seen by you" badge, which is CSS keyed on the tag, so no extra
field is needed.

### 5.2 The `inat::seen` tag

Tags (in addition to v1's `inat::iconic::…`, `inat::order::…` and `inat::family::…`):

| Tag | Meaning |
|---|---|
| `inat::set::<key>` | The species' set. |
| `inat::seen` | `seen_by` has at least one **research-grade** observation of this species, or of a taxon inside it, such as a subspecies. |

How it works:

- **Data source:** the same fetch as v1's `UserObservationsSource` (one request for 71
  observations). A species counts as seen if its taxon ID is the observation's taxon or
  one of its `ancestor_ids`.
- **Updates:** the tag is part of the note hash, so a species becomes "seen" in Anki on
  the next build after the user's observation reaches research grade.
- **Opting out:** `seen_by` can be set to `""` to turn it off. That matters when building
  a deck to share, where the tag means nothing to other people.
- **Filtered decks:** `-tag:inat::seen` gives a filtered deck of species you haven't seen
  yet.

## 6. Photo selection and licensing

For each species:

```
GET /v1/observations?taxon_id=<id>&place_id=6857&quality_grade=research
    &photo_license=cc0,cc-by,cc-by-sa&order_by=votes&per_page=30
```

1. Every photo still passes `licensing.is_usable(photo, observer_login, user_login,
   policy="shareable")`. The `photo_license` filter is a pre-filter, not the guarantee.
   Photos are checked one at a time, because one observation can mix licences.
2. Choose up to `photos_per_species` photos (default **2**), **from different
   observations, and preferably from different observers**. The first is the front photo.
3. **Fallbacks**, in order, while fewer than one usable photo has been found:
   1. **Trees only:** UK casual-grade cultivated observations with community agreement
      (`quality_grade=casual&captive=true&identifications=most_agree`; unverified, to be
      checked before building).
   2. Research grade with no `place_id`, meaning anywhere in the world.
   3. Skip the species and list it in the report.
4. **Choices are sticky.** Chosen photo IDs are stored in state and reused on later runs,
   so cards don't change on every rebuild. A photo is replaced only if its observation
   disappears, it loses research grade, or its licence changes to one that isn't usable.
   `--reselect-photos` forces a fresh choice.
5. **Licences are re-checked every run,** with one batched request per 200 chosen
   observations (`/v1/observations?id=…`), because users can change licences.

`licensing.py` gains a policy parameter:

| Policy | Accepts | Used by |
|---|---|---|
| `personal` | cc0, cc-by, cc-by-sa, cc-by-nc, cc-by-nc-sa, cc-by-nd, cc-by-nc-nd | Personal-study decks built from other people's photos (planned, none yet) |
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
    [--seen-by <login>]         overrides seen_by from the sets file; "" turns it off
    [--rerank] [--reselect-photos]
    [--photo-size large|medium] [--warn-threshold] [--max-downloads] [--yes]
    [--rate] [--dry-run] [--prune] [--force] [--verbose]
```

The cache is separate from v1's. Its `source_key` is `place:6857:uk-common`, which v1's
one-source-per-cache rule needs. State is a new schema with its own `schema_version`,
documented in `docs/state-schema-species.md`. It holds:

- set membership (sticky);
- the photos chosen for each species, with their observation IDs and licences;
- the note hash for each species;
- the same photo records, taxon ancestry, request counter and bandwidth window as v1.

The run report is v1's, plus:

- species per set, and how many of them are seen;
- species skipped for lack of photos, and species that used a fallback;
- species that dropped below the cut-off (sticky membership);
- the licence breakdown of the photos included.

## 8. Request and bandwidth budget

| Step | First run | Later runs |
|---|---|---|
| `species_counts`, one per set | 12 | 12 |
| Taxon ancestry and ID checks, 30 per request | about 14 | new species only |
| The user's observations for `seen` | 1 | 1 |
| Photo search, one per species | about 400, plus fallbacks | new or replaced species only |
| Licence re-check, 200 observations per request | 0 | about 4 |
| Photo downloads (400 × 2) | about 800 | new or replaced photos only |
| **Total** | **about 1,230 requests, about 21 min** | **about 20 requests** |

CC photos on the S3 host were about 212 KB at `large` in the v1 sample, so the first run
is about 170 to 530 MB. That's far under the 4.5 GB per hour limit. The first run goes
over the 200-photo warning threshold and asks for confirmation, and it can be resumed
(v1 section 6).

## 9. Code structure

The v1 split between modules with no I/O and thin I/O modules is unchanged:

- **`sets.py`** (no I/O): parse and validate set config and species lists, resolve
  overlaps and exclusions, apply sticky membership, and work out which species are seen.
- **`selection.py`** (no I/O): rank candidates, filter by licence policy, choose photos
  for variety, apply fallbacks, and keep earlier choices.
- **`render_species.py`** (no I/O): species → note fields, tags and hash.
- **`sources.py`:** adds `PlaceSpeciesSource` (`species_counts` and photo search), and
  reuses `UserObservationsSource` for `seen`.
- **`deck.py`:** gains the species model, derived deck IDs, the deck description and
  multi-deck packages. genanki's `Package` accepts a list of decks.
- **`cli.py`:** adds the `species` subcommand, and shares the throttle, client, media
  cache and report code with `sync`.

## 10. Testing

As in v1, tests never touch the network: they use recorded fixtures and a fake clock.
Add fixtures for `species_counts`, licence-filtered observations (including one that
mixes licences), a species/complex name clash, and hybrids.

Required cases:

- **Licensing:** each policy against every licence code; shareable rejects all NC and ND
  codes and `null`; the owner override.
- **Sets:**
  - an overlap fails the build;
  - `exclude_sets` removes species;
  - an unknown key fails, as does a duplicate key;
  - descendants returned for a species list are filtered out;
  - hybrids are kept for list sets;
  - an inactive ID in a species list fails the build.
- **Sticky membership:** a species below the cut-off stays; `--rerank` removes it and
  reports it.
- **Photo selection:**
  - two photos from different observations, preferring different observers;
  - a mixed-licence observation keeps only the usable photos;
  - the cultivated fallback for trees, then the worldwide fallback;
  - skipping a species that has no usable photo;
  - sticky choices, and replacement when a licence changes.
- **Seen:**
  - an observation of the species gives `inat::seen`;
  - so does an observation of a subspecies, through its ancestors;
  - non-research-grade observations don't count;
  - the tag change updates the note hash;
  - an empty `seen_by` gives no tags.
- **Identity:**
  - deck IDs are derived deterministically and pinned in tests;
  - the species GUID is the same whichever set the species is in;
  - the model ID is constant.
- **Package:** the `.apkg` has 12 decks with the right names; notes have the right
  model; the deck description is present; there are no duplicate GUIDs.

Acceptance, done manually:

1. The first run builds about 400 cards in 12 subdecks, every photo is CC0, CC BY or CC
   BY-SA, and every card shows credits with licence links.
2. Species you've observed (including Red Campion, House Sparrow and Hornbeam) carry
   `inat::seen`.
3. An immediate second run downloads no photos and makes about 20 requests.
4. Importing on top of the v1 deck leaves `iNaturalist::My observations` untouched.
5. Cards display correctly on desktop and mobile, in light and night mode.

## 11. Out of scope

- Rocks, minerals and geology of any kind.
- Places other than the UK. The design takes `place_id` as a parameter, but only 6857 is
  tested.
- Publishing to AnkiWeb automatically, and AnkiConnect.
- Sound cards, and the web app.

## 12. Open questions

1. **Insects and Grasses counts:** none were given, so this spec uses **50 insects** and
   **20 grasses**. The UK has about 59 butterfly species alone, so 50 insects will be mostly
   ladybirds, butterflies, common moths, bees and hoverflies.
2. **Grasses:** Poaceae only, or also sedges (Cyperaceae) and rushes (Juncaceae)? This
   spec uses Poaceae only. Sedges and rushes stay in Plants.
