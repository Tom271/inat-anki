# iNaturalist API notes

Findings from checking the live API on 2026-10-10 (SPEC section 2), using the
unauthenticated v1 API. The scripts that produced them are in `scripts/verify_api*.py`.
Raw responses are written to `scripts/out/` (git-ignored). Anonymised fixtures built
from them (`scripts/make_fixtures.py`) are in `tests/fixtures/`.

The test account has 71 research-grade observations (155 observations in total), 76
photos, no sound-only research-grade observations, and 65 distinct taxa.

## 1. UK place ID: confirmed

`GET /v1/places/autocomplete?q=United Kingdom` returns `id: 6857`, `name: "United Kingdom"`,
`admin_level: 0` as its first result. It is a config value (`preferred_place_id`), with
6857 as the default.

## 2. Common-name resolution: confirmed, with caveats

`locale=en&preferred_place_id=6857` on `/v1/observations` changes
`taxon.preferred_common_name` to the UK name where iNat has one. On the test account,
10 of 71 observations differ from `locale=en` alone:

| Scientific name | `locale=en` | `locale=en&preferred_place_id=6857` |
|---|---|---|
| *Medicago sativa* | Alfalfa | Lucerne |
| *Sturnus vulgaris* | European Starling | Common Starling |
| *Philaenus spumarius* | Meadow Spittlebug | Common Froghopper |
| *Araneus diadematus* | Cross Orbweaver | European Garden Spider |
| *Apioperdon pyriforme* | Pear-shaped Puffball | Stump Puffball |
| *Halyomorpha halys* | Brown Marmorated Stink Bug | Marbled shield bug |

- *Erithacus rubecula* gives "European Robin" and *Larus argentatus* gives "European
  Herring Gull" **with or without** the UK place. Most birds have no UK-specific name
  in iNat. For example, *Turdus merula* lists "Common Blackbird" and "Blackbird" as `en`
  names, but neither is tied to a place, so "Eurasian Blackbird" wins. This is iNat's
  data, not a bug in our request.
- `locale=en-GB` gives the same results as `locale=en` combined with the UK place.
  We use `locale=en`, as the spec says.
- Capitalisation is inconsistent in iNat's data ("red campion", "common hop", "Marbled
  shield bug"). Names are shown exactly as returned; we don't normalise case.
- **`taxon_name=` is a fuzzy match**: `taxon_name=Pica pica` returned an "Orange Chat"
  observation. Always filter by `taxon_id`. This matters for the future `--taxon-id`
  flag.
- Some taxa have no common name (`preferred_common_name` absent), for example
  *Cirsium monspessulanum*.

## 3. Photo URL sizes: confirmed on both hosts

`photos[].url` is the `square` size, for example
`https://static.inaturalist.org/photos/211141858/square.jpeg`. Replacing `square` with
`medium`, `large` or `original` returns 200 on both hosts.

| Host | square | medium | large |
|---|---|---|---|
| `static.inaturalist.org` (all photos on the test account) | 6.4 KB | 165 KB | 661 KB |
| `inaturalist-open-data.s3.amazonaws.com` (CC-licensed photos) | 3.0 KB | 70 KB | 212 KB |

- **Extensions vary**: `.jpeg` (older photos) and `.jpg` (newer). Take the extension from
  the URL when building media filenames, rather than assuming `.jpg`.
- The spec's 250 KB estimate for `large` can be well under the real size (661 KB in the
  sample). The estimate is replaced by real sizes once the cache has some.
- Observation photos in `photos[]` come in the same order as `observation_photos[].position`
  (checked on all 71 observations), so `photos[0]` is the lead photo.

### CORS (web-app risk from SPEC section 11)

- `inaturalist-open-data.s3.amazonaws.com` returns `Access-Control-Allow-Origin: *`.
- `static.inaturalist.org` returns **no** CORS header, on both `HEAD` and `GET` with an
  `Origin` header.

All-rights-reserved photos, which includes **all** of the test account's photos, are
served from `static.inaturalist.org`. So the browser app **cannot** `fetch()` the user's
own photos into an `.apkg`. It would have to fall back to hotlinked `<img src>`, or use a
proxy. This risk is now confirmed rather than hypothetical.

## 4. Photo licence fields: confirmed

All-rights-reserved photos have `license_code: null` and a populated `attribution`:
`"(c) <name>, all rights reserved"`. CC photos have, for example, `license_code: "cc-by"`
and `attribution: "(c) <name>, some rights reserved (CC BY)"`. Codes are lower case.

## 5. Time fields: confirmed, with one gotcha

- `time_observed_at`: ISO 8601 with the **local offset in effect at the time**, for example
  `"2022-07-03T15:51:33+01:00"` (BST) and `"2022-08-31T11:36:39+03:00"` (EEST). Its wall
  time matches `observed_on_string` (`"2022-07-03 15:51:33"`).
- `observed_time_zone`: an IANA name, for example `"Europe/London"`.
- `time_zone_offset`: the zone's **standard** offset (`"+00:00"` for London, even in
  July). **Do not use it.** It is not DST-aware.
- `observed_on`: `"YYYY-MM-DD"`, the local date.
- To render local time, parse `time_observed_at` with `datetime.fromisoformat` and use
  its wall time as is. If `time_observed_at` is null, render the date only, from
  `observed_on`.
- None of the test account's observations lack a time. The no-time case is a synthetic
  fixture.

## 6. Obscured locations: confirmed

On obscured observations (4 on the test account; all checked anonymously):

- `obscured: true` is the authoritative flag. It is set by `geoprivacy: "obscured"` **or**
  `taxon_geoprivacy: "obscured"` (seen with `geoprivacy: null`).
- `location` is still returned, but it's a **randomised** point, with
  `public_positional_accuracy` of roughly 25 to 31 km. `positional_accuracy` still shows
  the observer's original accuracy, which is misleading next to a randomised point.
- `place_guess` is coarsened, for example `"England, GB"` or `"Hertfordshire, England, GB"`.
- So: on obscured observations, render `Coordinates` empty and append
  `(location obscured)` to `Place`. On non-obscured observations, show
  `public_positional_accuracy` as the ± value.
- **Unverified:** there's no `geoprivacy: "private"` example on the test account. Private
  observations are expected to return `location: null` (and possibly a null
  `place_guess`) to anonymous clients, so the code treats them like the no-location
  fixture.

## 7. Taxon ancestors (for order and family tags)

- `/v1/observations` returns `taxon.ancestor_ids` but **not** `taxon.ancestors`. The
  `/v1/taxa` lookup is therefore the normal path, not the fallback.
- `GET /v1/taxa/{id1,id2,...}` (comma-separated, up to 30) returns each taxon with a full
  `ancestors[]` array (`id`, `name`, `rank`, `preferred_common_name`). One call per 30
  **observation taxa** gives order and family directly: 3 calls for 65 taxa, cached in
  state afterwards.
- The search form `GET /v1/taxa?id=...` returns the ancestors themselves, without nested
  ancestors. Using it would mean looking up every ancestor ID, so we don't.
- Some ancestors have no common name (for example *Pezizales*). Tags use scientific names
  only.

## 8. Common-species decks (v2): checked on 2026-10-10

From `scripts/verify_v2.py`. These checks underpin SPEC-v2.md.

- **Taxon IDs** (from `/v1/taxa?q=`, exact name match):
  - Aves 3; Fungi 47170 ("Fungi Including Lichens"); Lecanoromycetes 54743 ("Common
    Lichens");
  - Bryophyta 311249; Marchantiophyta 64615; Plantae 47126; Polypodiopsida 121943;
    Pinopsida 136329; Magnoliopsida 47124;
  - Reptilia 26036; Amphibia 20978; Mammalia 40151.
- **Ranking:** `/v1/observations/species_counts` with `place_id=6857`,
  `quality_grade=research`, `captive=false` and `rank=species` ranks species by count.
  The top UK birds are European Robin (43,195), Mallard (40,776) and Common Wood-Pigeon
  (34,668). There are 598 bird species in total.
- **Exclusions:** `without_taxon_id` works on `species_counts`. Fungi without
  Lecanoromycetes starts with Amanita muscaria and Auricularia auricula-judae.
  Lecanoromycetes starts with Xanthoria parietina, Evernia prunastri and Parmelia
  sulcata.
- **Default photos are often unusable for sharing.** Of the top 10 UK birds, 2 default
  photos are all rights reserved (Robin and Mute Swan) and 3 are NC or NC-SA.
- **Licence filter:** `photo_license=cc0,cc-by,cc-by-sa` on `/v1/observations` filters
  correctly. The UK Robin has 2,021 research-grade observations with such photos, all
  served from `inaturalist-open-data.s3.amazonaws.com`.
- **A list in `taxon_id` matches descendants.** On `species_counts`, a list of IDs
  returns every descendant of each listed taxon. A genus ID in the list brought back
  several *Artemisia* species, for example. Filter results down to the listed IDs.
- **Votes:** `order_by=votes` makes little difference, because most observations have 0
  or 1 votes.

### 8.1 Set definitions: checked on 2026-10-10

From `scripts/verify_v2_sets.py` and `scripts/verify_v2_trees_resolve.py`.

- **More taxon IDs:**
  - Insecta 47158; Poaceae 47434; Anthocerotophyta 56327; Rhodophyta 57774;
    Chlorophyta 50863; Ulvophyceae 51429; Phaeophyceae 48220;
  - Echinodermata 47549; Cnidaria 47534; Cirripedia 210289; Brachyura 121639;
    Polyplacophora 47429;
  - Littorinidae 48918; Patellidae 51740; Mytilidae 50600; Cardiidae 50597;
    Trochidae 53830; Muricidae 50766;
  - Domestic mammals: *Homo sapiens* 43584; *Canis familiaris* 47144; *Felis catus*
    118552; *Bos taurus* 74113; *Ovis aries* 121578; *Sus scrofa domesticus* 324492
    (a subspecies; *Sus domesticus* doesn't exist on iNat).
- **Research grade excludes captive and cultivated observations.** `species_counts` gives
  identical results with and without `captive=false`. So no domestic mammal appears in
  the top 15 UK research-grade mammals.
- **Planted trees** are casual grade (cultivated). With `quality_grade=research,casual`,
  monkey puzzle, Japanese cherry, Lawson cypress, box and common lime enter the top 50
  trees.
- **Name clash with "complex" taxa.** `/v1/taxa?q=Quercus robur` returns both the species
  (56133) and a same-named `complex` (1520309) that has more observations. The same
  applies to *Acer pseudoplatanus*, *Crataegus monogyna*, *Crataegus laevigata*,
  *Sambucus nigra*, *Viburnum opulus*, *Ulmus minor*, *Quercus ilex* and *Quercus
  petraea*. When resolving a name, prefer rank `species` or `hybrid`.
- **Hybrids** (*Platanus × hispanica*, *Tilia × europaea*, *Salix × fragilis*,
  *Ulmus × hollandica*) have rank `hybrid`. `rank=species` drops them; use
  `rank=species,hybrid`.
- **Limits:** `species_counts` returns 500 results with `per_page=500`, and
  `/v1/observations?id=` returned all 71 of 71 requested IDs.

### 8.2 Farm breeds: checked on 2026-10-10

From `scripts/verify_v2_breeds.py`, `verify_v2_breeds_2.py` and `verify_v2_breeds_3.py`.

- **iNat:** breeds aren't taxa. The "Breed" observation field (ID 3905; the similarly
  named "Breeding", ID 267, is unrelated) has 371 values worldwide, only 2 of them on UK
  cattle and 1 on UK sheep. UK observations with CC0, CC BY or CC BY-SA photos number 202
  for *Bos taurus*, 344 for *Ovis aries* and 32 for *Sus scrofa domesticus*, at any
  grade, with no breed information. They're unusable for breed cards.
- **Wikimedia Commons:** the MediaWiki API, `action=query&titles=Category:…&prop=categoryinfo`,
  checks up to 50 categories per request.
  - Categories exist for all 25 breeds in `lists/uk-farm-breeds.toml`. Some names
    differ from the obvious ones: `Angus cattle`, `Belgian Blue cattle`, `Texel (sheep)`,
    `Scottish Blackface`, `Charollais` and `Tamworth pig`.
  - `extmetadata.License` holds values such as `cc-by-sa-4.0`, `cc-by-2.0`,
    `cc-by-sa-3.0-de`, `cc0`, `pd` and `cc-sa-1.0`, or an empty string.
  - `extmetadata` can be an empty **list** rather than an object for some files, so
    handle that case.
- **Thin categories:** Lleyn sheep (2 files), Mule sheep (2) and Beef Shorthorn (4).
- **Wikipedia:** all 25 articles exist. British Blue is covered by "Belgian Blue", and
  the Mule by "Mule (sheep)".
