"""Aggregate per-file results into a summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wp_imgopt.processor import (
    ANIMATED,
    CONVERTED,
    ERROR,
    LARGER,
    UPTODATE,
    WOULD_CONVERT,
    Result,
)


def human_bytes(n: float) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # pragma: no cover


@dataclass
class Summary:
    results: list[Result] = field(default_factory=list)
    generated_skipped: int = 0
    excluded: int = 0
    dry_run: bool = False

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def scanned(self) -> int:
        return len(self.results)

    @property
    def errors(self) -> list[Result]:
        return [r for r in self.results if r.status == ERROR]

    @property
    def _converted(self) -> list[Result]:
        return [r for r in self.results if r.status == CONVERTED]

    @property
    def bytes_before(self) -> int:
        return sum(r.original_bytes for r in self._converted)

    @property
    def bytes_webp(self) -> int:
        return sum(r.outputs.get("webp", r.source_bytes) for r in self._converted)

    @property
    def bytes_avif(self) -> int:
        return sum(r.outputs.get("avif", 0) for r in self._converted)

    @property
    def bytes_saved(self) -> int:
        return self.bytes_before - self.bytes_webp

    @property
    def percent_saved(self) -> float:
        return round(100.0 * self.bytes_saved / self.bytes_before, 1) if self.bytes_before else 0.0

    @property
    def resized(self) -> int:
        return sum(1 for r in self.results if r.resized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "files_scanned": self.scanned,
            "converted": self.count(CONVERTED),
            "would_convert": self.count(WOULD_CONVERT),
            "up_to_date": self.count(UPTODATE),
            "not_smaller": self.count(LARGER),
            "animated_skipped": self.count(ANIMATED),
            "generated_sizes_skipped": self.generated_skipped,
            "excluded": self.excluded,
            "resized_originals": self.resized,
            "errors": self.count(ERROR),
            "bytes_before": self.bytes_before,
            "bytes_webp": self.bytes_webp,
            "bytes_avif": self.bytes_avif,
            "bytes_saved": self.bytes_saved,
            "percent_saved": self.percent_saved,
            "files": [r.to_dict() for r in self.results],
        }
