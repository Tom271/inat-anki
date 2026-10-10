# Anki identity: IDs that must never change

Anki matches imported notes to existing ones by **note GUID**. It matches note types by
**model ID**, and decks by **deck ID** and name. If any of these change, the next import
creates duplicates, or Anki treats the note type as a new schema. Either way, users lose
the link to their review history.

**Every tool that writes these decks must use exactly the values below.** That includes
this Python CLI and the future web app. Then a deck from either one updates the same
notes.

They're defined in [`src/inat_anki/deck.py`](../src/inat_anki/deck.py) and
[`src/inat_anki/model.py`](../src/inat_anki/model.py). `tests/test_deck.py` pins them.

## Constants

| What | Value |
|---|---|
| Model (note type) ID | `1707931833` |
| Model name | `iNaturalist observation` |
| Card template name | `Photo` |
| Deck ID | `1527378531` |
| Deck name | `iNaturalist::My observations` |
| Sort field | `ObsID` (index 0) |

Both IDs were generated once with `random.randrange(1 << 30, 1 << 31)`, as genanki
recommends.

## Fields

These are the fields in order. Never reorder, rename or remove one: Anki treats that as
a schema change. Adding a field at the end is possible, but it's disruptive too, so the
list includes fields for planned features.

1. `ObsID`
2. `FrontPhoto`
3. `ExtraPhotos`
4. `CommonName`
5. `ScientificName`
6. `Rank`
7. `ObservedOn`
8. `Place`
9. `Coordinates`
10. `ObsURL`
11. `TaxonID`
12. `Source`
13. `PhotoCredits`

## Note GUIDs

```python
genanki.guid_for("inat-obs", obs_id)
```

| Source | GUID inputs |
|---|---|
| A user's observations (v1) | `("inat-obs", obs_id)` |
| Future place-based decks | `("inat-place", place_key, taxon_id)`, a different namespace, so the two can never collide |

### Algorithm, for porting

This reproduces `genanki.guid_for` (genanki 0.13):

1. Join the values with `"__"` after converting each to a string, for example
   `"inat-obs__125757925"`.
2. Take the sha256 of the UTF-8 bytes, and read the **first 8 bytes** as a big-endian
   unsigned 64-bit integer.
3. Write that integer in base 91, most significant digit first, using this alphabet:

   ```
   abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&()*+,-./:;<=>?@[]^_`{|}~
   ```

**Check value:** `guid_for("inat-obs", 125757925)` is `e#pdPz/Wlu`.

In JavaScript, use `BigInt` for step 2, because the value doesn't fit in a `Number`.

## Media filenames

`inat_<photo_id>.<ext>`, with the extension taken from the photo URL (iNat uses both
`jpg` and `jpeg`). Anki's media folder is flat and every iNat URL ends in `large.jpg` or
similar, so the photo ID makes each name unique.

## Templates

The card templates and CSS are plain files in
[`src/inat_anki/templates/`](../src/inat_anki/templates/). They're inside the package so
that `uv tool install` ships them. The web app should use these files unchanged with
genanki-js.

## Known risk for the web app

A browser `fetch()` of a photo needs the photo host to send CORS headers. This was
checked on 2026-10-10 (see [api-notes.md](api-notes.md#cors-web-app-risk-from-spec-section-11)):

- `inaturalist-open-data.s3.amazonaws.com` (CC-licensed photos) sends
  `Access-Control-Allow-Origin: *`.
- `static.inaturalist.org` ("all rights reserved" photos) sends **no** CORS header.

A user's own photos are often "all rights reserved", so the web app can't download them
into an `.apkg`. The fallback is hotlinked `<img src>` URLs, which need no CORS but mean
the cards need a network connection. The other option is a proxy.
