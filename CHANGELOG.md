# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `--find-orphans` mode that reports `.webp` / `.avif` files whose source image was
  deleted, plus stale temp files from interrupted runs; `--delete` removes them, and
  `--json-report` records the result. With `--naming replace`, unmatched files are only
  reported as `unverified` and never deleted, since they may be real uploads.
- `--temp-min-age` to control when a leftover temp file counts as stale.

### Fixed
- `--json-report` creates missing parent folders and checks the path before processing starts, so a bad path exits with code 2 and a message instead of a traceback after a long run.

## [1.0.0] - 2026-11-08

### Added
- WebP conversion of JPEG and PNG files, with optional AVIF output.
- Optional resizing of oversized originals with a non-overwriting backup directory.
- EXIF orientation applied to pixels before metadata is stripped; ICC profile preserved.
- Detection and skipping of WordPress generated sizes such as `-150x150`.
- Parallel workers, dry-run mode, idempotent timestamp checks and an incremental manifest.
- Summary report table and JSON report.
- nginx and `.htaccess` snippet generators.
- `--sql-replace` mode that prints WP-CLI `search-replace` commands, including Elementor
  escaped-slash variants.
