# `state.json` schema (version 1)

`<cache-dir>/state.json` records what earlier runs downloaded and built. It's what makes
runs incremental. The future web app will store the same structure in IndexedDB.

- **Reading and writing:** `state.py` handles both. Writes are atomic: data goes to a
  temporary file in the same directory, is flushed to disk, then renamed into place. The
  tool saves state after every photo download, so an interruption loses at most one photo.
- **Refused files:** a file with a different `schema_version`, or one that won't parse, is
  refused rather than silently reset. Deleting the file and re-running rebuilds it, and
  photos already on disk are re-downloaded.

## Layout

```jsonc
{
  "schema_version": 1,
  "source_key": "user:tom1591",
  "photo_size": "large",
  "observations": {
    "124562758": {
      "updated_at": "2022-07-06T18:14:59+01:00",
      "photo_ids": [211141858],
      "note_hash": "91dc1f92…b213"
    }
  },
  "photos": {
    "211141858": {
      "filename": "inat_211141858.jpeg",
      "size": "large",
      "bytes": 661351,
      "license_code": null,
      "attribution": "(c) Tom H, all rights reserved",
      "sha256": "1c9a3ed2…b3e9"
    }
  },
  "taxa": {
    "5366": { "order": "Accipitriformes", "family": "Accipitridae" }
  },
  "requests": { "day": "2026-10-10", "count": 83 },
  "downloads": [[1791626006.797812, 661351]]
}
```

Object keys are IDs written as strings, because JSON keys must be strings.

## Fields

### Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Always `1` for this layout. Bump it, and add a migration, on any incompatible change. |
| `source_key` | string | The source this cache belongs to: `user:<login>`. A run for a different source is refused, so use another `--cache-dir`. |
| `photo_size` | string | The size used on the last run that downloaded photos: `large` or `medium`. |

### `observations`: notes that went into a deck

There's one entry per observation **included in a written `.apkg`**. Entries are written
only after the package has been written successfully.

| Field | Type | Meaning |
|---|---|---|
| `updated_at` | string | The observation's `updated_at` from the API, for information only. Change detection uses `note_hash`. |
| `photo_ids` | int[] | The observation's photo IDs in display order. The first is the front photo. |
| `note_hash` | string | sha256 (hex) of the rendered note's fields and tags (see below), or `""`. |

How the plan uses these entries:

- **New:** an observation that isn't here.
- **Changed:** `note_hash` differs from the newly rendered note.
- **Removed:** present here but missing from the fetch. Removed observations are reported
  once, then their entries are deleted.
- **`""` (empty hash):** the note was packaged before all its extra photos had been
  downloaded. An empty hash never matches, so the next run counts the note as changed and
  rebuilds it with the missing photos.

**Hash input:** `note_hash` is the hex sha256 of the UTF-8 encoding of this JSON:

```python
json.dumps({"fields": [...13 field values in order...], "tags": [...]}, ensure_ascii=False)
```

It uses Python's default separators, `", "` and `": "`. A port must reproduce the string
byte for byte, or every note will look changed on the first run after switching tools.

### `photos`: the photo cache

There's one entry per downloaded photo, keyed by iNat photo ID. A photo uploaded again
gets a new ID.

| Field | Type | Meaning |
|---|---|---|
| `filename` | string | `inat_<photo_id>.<ext>` in `<cache-dir>/media/`. The extension comes from the photo URL (`jpg`, `jpeg` or `png`). |
| `size` | string | `large` or `medium`. If it doesn't match the size requested now, the photo is downloaded again. |
| `bytes` | int | File size. Also used to estimate the size of future downloads. |
| `license_code` | string or null | iNat licence code, for example `cc-by`. `null` means all rights reserved. |
| `attribution` | string | iNat's attribution string, shown on the card. |
| `sha256` | string | Hex sha256 of the file. A file is valid only if it exists and both its size and sha256 match. Otherwise it's downloaded again. |

`--prune` deletes the files of photos that no current observation uses, and removes their
entries.

### `taxa`: the higher-taxonomy cache

This holds the order and family for each observed taxon, keyed by taxon ID, for use in
tags. It's filled from `GET /v1/taxa/{ids}`, 30 IDs per request, only for taxa not
already listed. Either value can be `null`.

### `requests`: the daily request counter

| Field | Type | Meaning |
|---|---|---|
| `day` | string | UTC date, `YYYY-MM-DD`. |
| `count` | int | Requests made on that day, including retries and photo downloads. It resets when the UTC day changes. Runs refuse to go past 11,000 unless `--force` is given. |

### `downloads`: the rolling-hour bandwidth window

This is a list of `[unix_seconds, bytes]` pairs, oldest first, one per downloaded photo.
Entries older than an hour are dropped when the window is checked. Before each download,
the tool pauses if the bytes in the last hour plus the expected download would go over
4.5 GB.
