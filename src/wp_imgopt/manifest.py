"""Incremental manifest so repeated runs only touch new or changed files."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 1


class Manifest:
    def __init__(self, path: Path, entries: dict[str, dict[str, Any]] | None = None) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = entries or {}

    @classmethod
    def load(cls, path: Path) -> Manifest:
        path = Path(path)
        if not path.is_file():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path)  # corrupt manifest: start over, never crash
        if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
            return cls(path)
        entries = data.get("entries")
        return cls(path, entries if isinstance(entries, dict) else {})

    def get(self, rel: str) -> dict[str, Any] | None:
        return self.entries.get(rel)

    def record(
        self,
        rel: str,
        *,
        size: int,
        mtime_ns: int,
        fingerprint: str,
        outputs: dict[str, int],
        skipped_formats: list[str],
    ) -> None:
        self.entries[rel] = {
            "size": size,
            "mtime_ns": mtime_ns,
            "fingerprint": fingerprint,
            "outputs": outputs,
            "skipped_formats": skipped_formats,
            "processed_at": int(time.time()),
        }

    def prune(self, root: Path) -> int:
        """Drop entries whose source file disappeared."""
        gone = [rel for rel in self.entries if not (Path(root) / rel).exists()]
        for rel in gone:
            del self.entries[rel]
        return len(gone)

    def save(self) -> None:
        payload = {"version": MANIFEST_VERSION, "entries": self.entries}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
