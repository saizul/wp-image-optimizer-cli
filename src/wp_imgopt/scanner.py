"""Discover source images inside a WordPress uploads tree."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from wp_imgopt.options import NAMING_APPEND, SOURCE_EXTENSIONS, Options

# WordPress appends -<width>x<height> to every generated intermediate size.
GENERATED_RE = re.compile(r"-\d+x\d+$")


def is_generated_size(path: Path) -> bool:
    """True for files such as photo-150x150.jpg created by WordPress."""
    return bool(GENERATED_RE.search(path.stem))


def output_path(src: Path, fmt: str, naming: str = NAMING_APPEND) -> Path:
    """Where the converted file for ``src`` lives."""
    if naming == NAMING_APPEND:
        return src.with_name(f"{src.name}.{fmt}")
    return src.with_suffix(f".{fmt}")


@dataclass
class ScanResult:
    candidates: list[Path] = field(default_factory=list)
    generated_skipped: int = 0
    excluded: int = 0


def _is_excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(Path(rel).name, p) for p in patterns)


def scan(root: Path, options: Options) -> ScanResult:
    """Walk ``root`` and return source images to process (sorted, deterministic)."""
    root = Path(root)
    result = ScanResult()
    backup = options.backup_dir.resolve() if options.backup_dir else None
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and (backup is None or (current / d).resolve() != backup)
        )
        for name in sorted(filenames):
            path = current / name
            if path.suffix.lower() not in SOURCE_EXTENSIONS or name.startswith("."):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if _is_excluded(rel, options.exclude):
                result.excluded += 1
                continue
            if not options.include_generated and is_generated_size(path):
                result.generated_skipped += 1
                continue
            result.candidates.append(path)
    return result


def find_collisions(paths: list[Path], options: Options) -> set[Path]:
    """With ``replace`` naming, a.jpg and a.png would both claim a.webp.

    The first file (in sorted order) wins; later ones are returned so the caller
    can report them instead of silently overwriting output.
    """
    seen: dict[Path, Path] = {}
    losers: set[Path] = set()
    for path in paths:
        key = output_path(path, "webp", options.naming)
        if key in seen:
            losers.add(path)
        else:
            seen[key] = path
    return losers
