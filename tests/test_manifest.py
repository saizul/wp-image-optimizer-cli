from __future__ import annotations

import json

from wp_imgopt.manifest import Manifest


def test_load_missing_returns_empty(tmp_path):
    assert Manifest.load(tmp_path / "m.json").entries == {}


def test_save_and_load_roundtrip(tmp_path):
    m = Manifest(tmp_path / "m.json")
    m.record(
        "a/b.jpg", size=10, mtime_ns=5, fingerprint="f", outputs={"webp": 4}, skipped_formats=[]
    )
    m.save()
    loaded = Manifest.load(tmp_path / "m.json")
    assert loaded.get("a/b.jpg")["outputs"] == {"webp": 4}
    assert loaded.get("a/b.jpg")["fingerprint"] == "f"


def test_corrupt_manifest_is_ignored(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{not json", encoding="utf-8")
    assert Manifest.load(path).entries == {}


def test_wrong_version_is_ignored(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"version": 99, "entries": {"x": {}}}), encoding="utf-8")
    assert Manifest.load(path).entries == {}


def test_prune_removes_deleted_sources(tmp_path):
    (tmp_path / "keep.jpg").write_bytes(b"x")
    m = Manifest(tmp_path / "m.json")
    for rel in ("keep.jpg", "gone.jpg"):
        m.record(rel, size=1, mtime_ns=1, fingerprint="f", outputs={}, skipped_formats=[])
    assert m.prune(tmp_path) == 1
    assert list(m.entries) == ["keep.jpg"]


def test_save_is_atomic_no_tmp_left(tmp_path):
    m = Manifest(tmp_path / "m.json")
    m.save()
    assert [p.name for p in tmp_path.iterdir()] == ["m.json"]
