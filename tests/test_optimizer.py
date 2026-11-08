from __future__ import annotations

import json

import pytest

from conftest import save_jpeg, save_png
from wp_imgopt.optimizer import OptimizerError, run
from wp_imgopt.options import MANIFEST_NAME, Options
from wp_imgopt.processor import avif_available


def test_run_converts_tree(sample_tree):
    summary = run(sample_tree, Options(workers=2))
    assert summary.count("converted") == 3
    assert summary.generated_skipped == 1
    assert (sample_tree / "2024/05/photo.jpg.webp").is_file()
    assert (sample_tree / "2024/05/logo.png.webp").is_file()
    assert not (sample_tree / "2024/05/photo-150x150.jpg.webp").exists()


def test_run_include_generated(sample_tree):
    run(sample_tree, Options(include_generated=True))
    assert (sample_tree / "2024/05/photo-150x150.jpg.webp").is_file()


def test_second_run_is_noop(sample_tree):
    run(sample_tree, Options())
    again = run(sample_tree, Options())
    assert again.count("converted") == 0
    assert again.count("uptodate") == 3


def test_manifest_written_and_pruned(sample_tree):
    run(sample_tree, Options())
    manifest = json.loads((sample_tree / MANIFEST_NAME).read_text())
    assert "2024/05/photo.jpg" in manifest["entries"]
    (sample_tree / "2024/05/photo.jpg").unlink()
    run(sample_tree, Options())
    manifest = json.loads((sample_tree / MANIFEST_NAME).read_text())
    assert "2024/05/photo.jpg" not in manifest["entries"]


def test_no_manifest_option(sample_tree):
    run(sample_tree, Options(use_manifest=False))
    assert not (sample_tree / MANIFEST_NAME).exists()


def test_custom_manifest_path(sample_tree, tmp_path):
    target = tmp_path / "elsewhere.json"
    run(sample_tree, Options(manifest_path=target))
    assert target.is_file()


def test_dry_run_writes_no_manifest_or_outputs(sample_tree):
    summary = run(sample_tree, Options(dry_run=True))
    assert summary.count("would_convert") == 3
    assert not list(sample_tree.rglob("*.webp"))
    assert not (sample_tree / MANIFEST_NAME).exists()


def test_changing_quality_reprocesses(sample_tree):
    run(sample_tree, Options(quality=80))
    summary = run(sample_tree, Options(quality=40))
    assert summary.count("converted") == 3


def test_larger_result_remembered_in_manifest(uploads):
    from conftest import make_photo

    make_photo().save(uploads / "t.jpg", "JPEG", quality=10)
    first = run(uploads, Options(quality=100))
    assert first.count("larger") == 1
    second = run(uploads, Options(quality=100))
    assert second.count("uptodate") == 1


def test_errors_are_reported_and_others_continue(sample_tree):
    (sample_tree / "broken.jpg").write_bytes(b"nope")
    summary = run(sample_tree, Options())
    assert len(summary.errors) == 1
    assert summary.count("converted") == 3


def test_collision_with_replace_naming(uploads):
    save_jpeg(uploads / "a.jpg")
    save_png(uploads / "a.png")
    summary = run(uploads, Options(naming="replace"))
    assert len(summary.errors) == 1
    assert "collides" in summary.errors[0].message


def test_single_worker_matches_parallel(tmp_path):
    results = []
    for workers in (1, 4):
        root = tmp_path / f"w{workers}"
        for i in range(6):
            save_jpeg(root / f"i{i}.jpg", 200 + i, 100)
        s = run(root, Options(workers=workers))
        results.append([(r.rel, r.status, r.outputs) for r in s.results])
    assert results[0] == results[1]


def test_results_sorted(sample_tree):
    summary = run(sample_tree, Options())
    rels = [r.rel for r in summary.results]
    assert rels == sorted(rels)


def test_not_a_directory(tmp_path):
    with pytest.raises(OptimizerError):
        run(tmp_path / "missing", Options())


def test_invalid_quality(uploads):
    with pytest.raises(ValueError):
        run(uploads, Options(quality=0))


@pytest.mark.skipif(avif_available(), reason="only meaningful without AVIF support")
def test_avif_requested_but_unavailable(uploads):
    with pytest.raises(OptimizerError, match="AVIF"):
        run(uploads, Options(avif=True))


def test_resize_with_backup_in_tree(uploads, tmp_path):
    save_jpeg(uploads / "big.jpg", 1200, 600)
    backup = tmp_path / "bk"
    summary = run(uploads, Options(max_width=600, backup_dir=backup))
    assert summary.resized == 1
    assert (backup / "big.jpg").is_file()
    again = run(uploads, Options(max_width=600, backup_dir=backup))
    assert again.resized == 0 and again.count("uptodate") == 1
