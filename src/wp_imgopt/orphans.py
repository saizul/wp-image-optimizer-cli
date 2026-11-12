"""Find (and optionally remove) converted files whose source image is gone.

When an image is deleted from the Media Library, WordPress removes the original and
its generated sizes but knows nothing about ``photo.jpg.webp``. Over time the uploads
tree fills with these orphans. Interrupted runs (SIGKILL, power loss) can also leave
temporary ``.photo.jpg.webp.<pid>.<tid>.tmp`` files behind.

Safety model:

* ``append`` naming (``photo.jpg.webp``) is unambiguous: the source name is the file
  name minus the last extension, so a missing source means a real orphan.
* ``replace`` naming (``photo.webp``) is ambiguous: a WebP the editor uploaded on
  purpose looks exactly like a converted twin. Such files are reported as
  ``unverified`` and are never deleted.
* Stale temp files are only reported when they are older than ``min_age`` seconds,
  so a run that is still in progress is never disturbed.
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wp_imgopt.options import NAMING_APPEND, SOURCE_EXTENSIONS

OUTPUT_EXTENSIONS = (".webp", ".avif")

ORPHAN = "orphan"  # converted twin whose source no longer exists (safe to delete)
UNVERIFIED = "unverified"  # replace naming: may be an editor upload, never deleted
STALE_TEMP = "stale-temp"  # leftover temp file from an interrupted run

# Matches the name produced by processor._tmp_name: .<dest>.<pid>.<thread-id>.tmp
TEMP_RE = re.compile(r"^\..+\.(?:webp|avif|jpe?g|png)\.\d+\.\d+\.tmp$", re.IGNORECASE)

DEFAULT_TEMP_MIN_AGE = 3600


@dataclass
class Orphan:
    rel: str
    kind: str
    size: int
    expected_source: str | None = None

    @property
    def deletable(self) -> bool:
        return self.kind in (ORPHAN, STALE_TEMP)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.rel,
            "kind": self.kind,
            "bytes": self.size,
            "expected_source": self.expected_source,
            "deletable": self.deletable,
        }


@dataclass
class OrphanReport:
    items: list[Orphan] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Orphan]:
        return [o for o in self.items if o.kind == kind]

    @property
    def reclaimable_bytes(self) -> int:
        return sum(o.size for o in self.items if o.deletable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "orphans": len(self.of_kind(ORPHAN)),
            "unverified": len(self.of_kind(UNVERIFIED)),
            "stale_temp": len(self.of_kind(STALE_TEMP)),
            "reclaimable_bytes": self.reclaimable_bytes,
            "deleted": self.deleted,
            "failed": [{"path": p, "error": e} for p, e in self.failed],
            "items": [o.to_dict() for o in self.items],
        }


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(Path(rel).name, p) for p in patterns)


def _has_source(stem_path: Path, names_lower: set[str]) -> bool:
    """For replace naming: does any photo.jpg / photo.JPEG / photo.png sibling exist?"""
    stem = stem_path.name.lower()
    return any(f"{stem}{ext}" in names_lower for ext in SOURCE_EXTENSIONS)


def find_orphans(
    root: Path,
    naming: str = NAMING_APPEND,
    *,
    exclude: tuple[str, ...] = (),
    backup_dir: Path | None = None,
    temp_min_age: float = DEFAULT_TEMP_MIN_AGE,
    now: float | None = None,
) -> OrphanReport:
    """Walk ``root`` and classify converted files that no longer have a source."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    if temp_min_age < 0:
        raise ValueError("temp_min_age must not be negative")
    now = time.time() if now is None else now
    backup = backup_dir.resolve() if backup_dir else None
    report = OrphanReport()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and (backup is None or (current / d).resolve() != backup)
        )
        names = set(filenames)
        names_lower = {n.lower() for n in filenames}
        for name in sorted(filenames):
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if _excluded(rel, exclude):
                continue

            if TEMP_RE.match(name):
                stat = path.stat()
                if now - stat.st_mtime >= temp_min_age:
                    report.items.append(Orphan(rel, STALE_TEMP, stat.st_size))
                continue

            if name.startswith(".") or path.suffix.lower() not in OUTPUT_EXTENSIONS:
                continue

            inner = Path(name[: -len(path.suffix)])  # photo.jpg.webp -> photo.jpg
            if naming == NAMING_APPEND:
                if inner.suffix.lower() not in SOURCE_EXTENSIONS:
                    continue  # a plain photo.webp upload, not ours
                if inner.name in names:
                    continue
                source = (current / inner.name).relative_to(root).as_posix()
                report.items.append(Orphan(rel, ORPHAN, path.stat().st_size, source))
            else:
                if inner.suffix.lower() in SOURCE_EXTENSIONS:
                    continue  # append-style name while scanning with replace naming
                if _has_source(inner, names_lower):
                    continue
                report.items.append(Orphan(rel, UNVERIFIED, path.stat().st_size))

    report.items.sort(key=lambda o: o.rel)
    return report


def delete_orphans(root: Path, report: OrphanReport) -> OrphanReport:
    """Remove every deletable item in ``report``; unverified files are left alone."""
    root = Path(root)
    for item in report.items:
        if not item.deletable:
            continue
        target = root / item.rel
        try:
            target.unlink()
        except FileNotFoundError:
            continue  # already gone: nothing to do
        except OSError as exc:
            report.failed.append((item.rel, exc.strerror or str(exc)))
        else:
            report.deleted.append(item.rel)
    return report
