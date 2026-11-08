from __future__ import annotations

from pathlib import Path

import pytest

from conftest import save_jpeg, save_png
from wp_imgopt.options import Options
from wp_imgopt.scanner import find_collisions, is_generated_size, output_path, scan


@pytest.mark.parametrize(
    "name,expected",
    [
        ("photo-150x150.jpg", True),
        ("photo-1024x768.png", True),
        ("photo-scaled.jpg", False),
        ("photo.jpg", False),
        ("photo-e1700000000000.jpg", False),
        ("2024-05-12x30.jpg", True),
        ("sizes-150x.jpg", False),
        ("a-1x1.jpeg", True),
    ],
)
def test_is_generated_size(name, expected):
    assert is_generated_size(Path(name)) is expected


def test_output_path_append():
    assert output_path(Path("/u/a.jpg"), "webp") == Path("/u/a.jpg.webp")


def test_output_path_replace():
    assert output_path(Path("/u/a.JPG"), "avif", "replace") == Path("/u/a.avif")


def test_scan_finds_originals_and_skips_generated(sample_tree):
    res = scan(sample_tree, Options())
    names = [p.name for p in res.candidates]
    assert names == ["logo.png", "photo.jpg", "banner.jpeg"]
    assert res.generated_skipped == 1


def test_scan_include_generated(sample_tree):
    res = scan(sample_tree, Options(include_generated=True))
    assert "photo-150x150.jpg" in [p.name for p in res.candidates]
    assert res.generated_skipped == 0


def test_scan_ignores_other_extensions(uploads):
    (uploads / "doc.pdf").write_bytes(b"%PDF")
    (uploads / "pic.webp").write_bytes(b"RIFF")
    (uploads / "anim.gif").write_bytes(b"GIF89a")
    assert scan(uploads, Options()).candidates == []


def test_scan_case_insensitive_extension(uploads):
    save_jpeg(uploads / "UPPER.JPG")
    assert len(scan(uploads, Options()).candidates) == 1


def test_scan_skips_hidden_dirs_and_files(uploads):
    save_jpeg(uploads / ".cache/x.jpg")
    save_jpeg(uploads / ".hidden.jpg")
    assert scan(uploads, Options()).candidates == []


def test_scan_exclude_glob(sample_tree):
    res = scan(sample_tree, Options(exclude=("2024/06/*",)))
    assert "banner.jpeg" not in [p.name for p in res.candidates]
    assert res.excluded == 1


def test_scan_exclude_by_basename(sample_tree):
    res = scan(sample_tree, Options(exclude=("logo.*",)))
    assert "logo.png" not in [p.name for p in res.candidates]


def test_scan_skips_backup_dir_inside_root(uploads):
    save_jpeg(uploads / "a.jpg")
    save_jpeg(uploads / "backup/a.jpg")
    res = scan(uploads, Options(backup_dir=uploads / "backup"))
    assert [p.name for p in res.candidates] == ["a.jpg"]
    assert len(res.candidates) == 1


def test_scan_skips_symlinks(uploads, tmp_path):
    real = save_jpeg(tmp_path / "outside.jpg")
    try:
        (uploads / "link.jpg").symlink_to(real)
    except OSError:
        pytest.skip("symlinks unsupported")
    assert scan(uploads, Options()).candidates == []


def test_find_collisions_replace_naming(uploads):
    a = save_jpeg(uploads / "a.jpg")
    b = save_png(uploads / "a.png")
    lost = find_collisions([a, b], Options(naming="replace"))
    assert lost == {b}


def test_no_collisions_with_append_naming(uploads):
    a = save_jpeg(uploads / "a.jpg")
    b = save_png(uploads / "a.png")
    assert find_collisions([a, b], Options()) == set()
