# Species `state.json` schema (version 1)

`inat-anki species` keeps its own state in `<cache-dir>/state.json`. The default cache is
`inat-cache-species/`, separate from v1's `inat-cache/`. The file has `"kind":
"species"`, so v1 and v2 refuse each other's state. It's written atomically after every
photo download, as in v1 (see [state-schema.md](state-schema.md)).

```jsonc
{
  "schema_version": 1,
  "kind": "species",
  "source_key": "place:6857:uk-common",       // place and sets-file name
  "photo_size": "large",
  "members": {                                // set key -> members, in deck order (sticky)
    "birds": [13094, 6930],                   //   taxon IDs
    "farm-breeds": ["cattle/hereford"]        //   or breed keys
  },
  "counts": { "13094": 43195 },               // last UK count per taxon
  "taxa": {                                   // names and ancestry for card fields and tags
    "13094": { "name": "Erithacus rubecula", "rank": "species",
               "common_name": "European Robin", "iconic": "Aves",
               "order": "Passeriformes", "family": "Muscicapidae" }
  },
  "choices": {                                // card key -> chosen photos, front first
    "inat-place:6857:13094": [ { "key": "inat:75847867", "source_id": "47813302" } ],
    "breed:cattle/hereford": [ { "key": "commons:File:Hereford Dunblane.jpg",
                                 "source_id": "File:Hereford Dunblane.jpg" } ]
  },
  "notes": { "inat-place:6857:13094": "9f2c…" },   // card hash, or "" to rebuild next run
  "photos": {                                 // photo key -> cached file (v1's photo record)
    "inat:75847867": { "filename": "inat_75847867.jpeg", "size": "large", "bytes": 212000,
                       "license_code": "cc0", "attribution": "<credit html>",
                       "sha256": "…" }
  },
  "requests": { "day": "2026-10-10", "count": 1310 },
  "downloads": [[1791640000.1, 212000]]
}
```

## How the fields are used

- **Card keys** are the GUID parts joined with `:`: `inat-place:<place>:<taxon_id>` for
  species, and `breed:<breed key>` for breeds.
- **Photo keys** are `inat:<photo_id>` or `commons:<file title>`. iNat files are named
  `inat_<photo_id>.<ext>`. Commons files are named `commons_<first 16 hex digits of
  sha256(title)>.jpg`.
- **`members`:** set membership is sticky. A run only adds species until each set reaches
  its `count`. `--rerank` replaces the list. `--only` leaves other sets' lists unchanged.
- **`choices`:** each run re-checks these: iNat observations in batches of 200 IDs, and
  Commons files in batches of 50 titles. A choice is kept while its photo is still
  present and allowed under the shareable licence policy. `--reselect-photos` ignores
  them.
- **`notes`:** written only after a successful `.apkg` write. An empty hash means the card
  was packaged without all its photos, and it's rebuilt once they arrive.
- **`requests` and `downloads`:** the same counters as v1, shared by iNat and Commons
  requests.
