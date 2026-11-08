"""Run configuration shared by every stage of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SOURCE_EXTENSIONS = (".jpg", ".jpeg", ".png")
NAMING_APPEND = "append"  # photo.jpg -> photo.jpg.webp (default, collision free)
NAMING_REPLACE = "replace"  # photo.jpg -> photo.webp
MANIFEST_NAME = ".wp-imgopt-manifest.json"


@dataclass
class Options:
    quality: int = 80
    avif: bool = False
    avif_quality: int = 60
    lossless_png: bool = False
    max_width: int | None = None
    jpeg_quality: int = 85
    backup_dir: Path | None = None
    include_generated: bool = False
    naming: str = NAMING_APPEND
    workers: int = 4
    dry_run: bool = False
    force: bool = False
    keep_larger: bool = False
    use_manifest: bool = True
    manifest_path: Path | None = None
    exclude: tuple[str, ...] = ()

    def validate(self) -> None:
        for name in ("quality", "avif_quality", "jpeg_quality"):
            value = getattr(self, name)
            if not 1 <= value <= 100:
                raise ValueError(f"{name} must be between 1 and 100 (got {value})")
        if self.max_width is not None and self.max_width < 16:
            raise ValueError("max_width must be at least 16 pixels")
        if self.naming not in (NAMING_APPEND, NAMING_REPLACE):
            raise ValueError(f"naming must be '{NAMING_APPEND}' or '{NAMING_REPLACE}'")
        if self.workers < 1:
            raise ValueError("workers must be at least 1")

    @property
    def formats(self) -> tuple[str, ...]:
        return ("webp", "avif") if self.avif else ("webp",)

    def fingerprint(self) -> str:
        """Settings that change the encoded bytes; used to invalidate the manifest."""
        parts = [
            f"q={self.quality}",
            f"aq={self.avif_quality if self.avif else 0}",
            f"ll={int(self.lossless_png)}",
            f"mw={self.max_width or 0}",
            f"jq={self.jpeg_quality if self.max_width else 0}",
            f"n={self.naming}",
        ]
        return ";".join(parts)
