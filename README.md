# wp-image-optimizer-cli

[![CI](https://github.com/saizul/wp-image-optimizer-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/wp-image-optimizer-cli/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

`wp-imgopt` bulk-optimizes a WordPress `wp-content/uploads` tree from the command
line. It writes WebP (and optionally AVIF) copies next to your originals, can shrink
oversized originals with a backup, and then helps you actually *serve* the new files
with ready-made nginx / `.htaccess` snippets and safe WP-CLI `search-replace` commands.

It is built for the boring, risky parts of image optimization: re-running is
idempotent, one corrupt file never aborts a run, writes are atomic, and nothing
touches your database unless you copy the printed commands yourself.

## Features

- JPEG / PNG to **WebP**, plus optional **AVIF**, written next to the originals
- Optional **resize** of originals wider than `--max-width` (aspect ratio kept, never
  upscales) with a **backup directory** that is never overwritten
- Skips WordPress generated sizes (`photo-150x150.jpg`) unless `--include-generated`
- EXIF orientation is **applied to the pixels first**, then all metadata is stripped
  (the ICC colour profile is kept so colours do not shift)
- Configurable quality, lossless PNG mode, **parallel workers**, **dry run**
- **Idempotent**: skips a file when its outputs are newer than the source
- **Incremental manifest** (`.wp-imgopt-manifest.json`) remembers what was done, with
  which settings, and which files were not worth converting
- Summary report (files, bytes saved, %) as a table and optional JSON
- `--nginx` / `--htaccess` snippets that serve `.webp` (or `.avif`) only when the
  browser's `Accept` header allows it
- `--sql-replace` prints a reviewed list of `wp search-replace` commands for chosen
  image URLs, including the escaped-slash form Elementor stores in `_elementor_data`

## Install

```bash
pip install .            # or: pip install -e ".[dev]" for development
pip install ".[avif]"    # only needed on Pillow < 11.3 for AVIF output
```

Requires Python 3.10+. Dependencies: Pillow, rich (and `pillow-avif-plugin` for AVIF on
older Pillow releases; Pillow 11.3+ can write AVIF by itself).

## Usage

```bash
# 1. See what would happen, change nothing
wp-imgopt /var/www/site/wp-content/uploads --dry-run

# 2. Convert to WebP at quality 80
wp-imgopt /var/www/site/wp-content/uploads

# 3. WebP + AVIF, and shrink anything wider than 1920px (originals backed up first)
wp-imgopt /var/www/site/wp-content/uploads --avif --max-width 1920 \
    --backup-dir /var/backups/uploads-originals -j 8
```

Example output:

```text
                wp-imgopt summary
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Metric                     ┃            Value ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Files scanned              │                2 │
│ Converted                  │                2 │
│ WP generated sizes skipped │                1 │
│ Originals resized          │                1 │
│ Original bytes             │         531.6 KB │
│ WebP bytes                 │          24.0 KB │
│ AVIF bytes                 │          15.0 KB │
│ Saved                      │ 507.6 KB (95.5%) │
└────────────────────────────┴──────────────────┘
```

Running the same command again reports everything as "Already up to date".

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `-q, --quality N` | 80 | WebP quality (1-100) |
| `--avif`, `--avif-quality N` | off, 60 | also write AVIF |
| `--lossless-png` | off | encode PNG sources as lossless WebP |
| `--naming append\|replace` | `append` | `a.jpg.webp` (safe) or `a.webp` |
| `--keep-larger` | off | keep a converted file even when it is not smaller |
| `--max-width N` | none | shrink originals wider than N pixels |
| `--jpeg-quality N` | 85 | quality used when re-saving resized JPEGs |
| `--backup-dir DIR` | none | copy originals here before resizing |
| `--include-generated` | off | also process `-150x150` style sizes |
| `--exclude GLOB` | none | skip paths (repeatable), matched on relative path or file name |
| `-j, --workers N` | 4 | parallel workers |
| `-n, --dry-run` | off | analyse only; writes no images and no manifest |
| `--force` | off | ignore timestamps and manifest |
| `--no-manifest`, `--manifest PATH` | on | manifest handling |
| `--json-report PATH` | none | write the full per-file report as JSON |
| `--quiet` | off | no progress or table |

Exit codes: `0` success, `1` one or more files failed (or nothing to replace in
`--sql-replace`), `2` bad usage or configuration.

### How "bytes saved" is calculated

For every file converted in the current run: original size before any resize minus the
WebP size. Because the encode happens from the already-resized pixels, resize savings are
included. AVIF bytes are reported separately. Files that were already up to date are not
counted again.

### Why `append` naming is the default

`photo.jpg` and `photo.png` can both exist in a Media Library. Replacing the extension
would make both claim `photo.webp`. Appending (`photo.jpg.webp`) cannot collide and maps
one-to-one to the original. `--naming replace` is available, and collisions are reported
as errors instead of silently overwriting.

## Serving the files

### nginx

```bash
wp-imgopt --nginx            # add --avif for AVIF first, --naming replace if you use it
```

Put the `map` blocks in the `http { }` context and the `location` in your `server { }`:

```nginx
map $http_accept $webp_ext {
    default "";
    "~*image/webp" ".webp";
}

location ~* \.(?:jpe?g|png)$ {
    add_header Vary Accept;
    expires 30d;
    try_files $uri$webp_ext $uri =404;
}
```

If the `.webp` twin is missing, nginx falls back to the original.

### Apache

```bash
wp-imgopt --htaccess >> /var/www/site/wp-content/uploads/.htaccess
```

The block uses `mod_rewrite` to serve `file.jpg.webp` when the browser sends
`Accept: image/webp` and the file exists, sets the right MIME type and adds
`Vary: Accept` so CDNs and caches keep both variants apart.

## Switching URLs stored in the database

Serving through a rewrite is usually enough. If you also want the database to point to
`.webp` for specific images, `--sql-replace` prints commands; it never connects to your
site.

```bash
wp-imgopt /var/www/site/wp-content/uploads --sql-replace \
    --site-url https://example.com --only '2024/05/*' --elementor
```

Only files whose converted twin already exists on disk are included. You can also pass a
list with `--url-list urls.txt` (full URLs or paths relative to uploads, one per line).
The output is a numbered script: database backup, a `--dry-run` pass, the real pass, then
cache flushes (`wp elementor flush-css` with `--elementor`). Each command uses
`--skip-columns=guid`, `--precise` (safe for serialized data) and `--report-changed-only`.
Every argument is shell-quoted. Run the apply block only once: repeating it would turn
`.jpg.webp` into `.jpg.webp.webp`.

## Safety notes

- Originals are only modified when `--max-width` is set and the image is wider. Use
  `--backup-dir` and keep it outside the uploads tree (or inside; it is skipped).
- Every output is written to a temporary file and moved into place, so an interrupted run
  never leaves a half-written `.webp`.
- Animated PNGs are skipped. Symlinks and dot-directories are ignored.
- Test on a copy first and keep a real backup. This tool is provided as is.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT. Copyright (c) 2026 Saizul Amin - [saizul.com](https://saizul.com)
