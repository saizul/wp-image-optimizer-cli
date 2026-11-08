from __future__ import annotations

import os

import pytest
from PIL import Image

from conftest import make_photo, save_jpeg, save_png
from wp_imgopt.options import Options
from wp_imgopt.processor import (
    ANIMATED,
    CONVERTED,
    ERROR,
    LARGER,
    UPTODATE,
    WOULD_CONVERT,
    avif_available,
    normalize_mode,
    process_image,
    target_size,
)

needs_avif = pytest.mark.skipif(not avif_available(), reason="AVIF encoder not installed")


def run_one(path, root, **kw):
    return process_image(path, root, Options(**kw))


def test_jpeg_to_webp(uploads):
    src = save_jpeg(uploads / "a.jpg")
    res = run_one(src, uploads)
    out = uploads / "a.jpg.webp"
    assert res.status == CONVERTED
    assert out.is_file()
    with Image.open(out) as im:
        assert im.format == "WEBP"
        assert im.size == (320, 200)
    assert res.outputs["webp"] == out.stat().st_size < src.stat().st_size


def test_png_with_alpha_keeps_alpha(uploads):
    src = save_png(uploads / "l.png", mode="RGBA")
    assert run_one(src, uploads).status == CONVERTED
    with Image.open(uploads / "l.png.webp") as im:
        assert "A" in im.getbands()


def test_palette_png_with_transparency(uploads):
    img = Image.new("P", (200, 200))
    img.putpalette([i % 256 for i in range(768)])
    img.info["transparency"] = 0
    for x in range(200):
        for y in range(200):
            img.putpixel((x, y), (x * y) % 256)
    img.save(uploads / "p.png", transparency=0)
    assert run_one(uploads / "p.png", uploads).status in (CONVERTED, LARGER)


def test_grayscale_png(uploads):
    src = save_png(uploads / "g.png", mode="L")
    res = run_one(src, uploads)
    assert res.status == CONVERTED
    assert (uploads / "g.png.webp").is_file()


def test_cmyk_jpeg(uploads):
    make_photo().convert("CMYK").save(uploads / "c.jpg", "JPEG", quality=95)
    res = run_one(uploads / "c.jpg", uploads)
    assert res.status == CONVERTED


def test_replace_naming(uploads):
    src = save_jpeg(uploads / "a.jpg")
    run_one(src, uploads, naming="replace")
    assert (uploads / "a.webp").is_file()
    assert not (uploads / "a.jpg.webp").exists()


def test_originals_untouched_without_max_width(uploads):
    src = save_jpeg(uploads / "a.jpg")
    before = src.read_bytes()
    run_one(src, uploads)
    assert src.read_bytes() == before


def test_quality_changes_size(uploads):
    src = save_jpeg(uploads / "a.jpg")
    low = run_one(src, uploads, quality=30, force=True).outputs["webp"]
    high = run_one(src, uploads, quality=95, force=True).outputs["webp"]
    assert low < high


def test_lossless_png(uploads):
    src = save_png(uploads / "a.png")
    res = run_one(src, uploads, lossless_png=True)
    assert res.status == CONVERTED
    with Image.open(uploads / "a.png.webp") as out, Image.open(src) as orig:
        assert list(out.convert("RGB").getdata()) == list(orig.convert("RGB").getdata())


def tiny_jpeg(path):
    """A heavily compressed JPEG that a q100 WebP cannot beat."""
    make_photo().save(path, "JPEG", quality=10)
    return path


def test_not_smaller_is_skipped(uploads):
    src = tiny_jpeg(uploads / "t.jpg")
    res = run_one(src, uploads, quality=100)
    assert res.status == LARGER
    assert not (uploads / "t.jpg.webp").exists()


def test_keep_larger(uploads):
    src = tiny_jpeg(uploads / "t.jpg")
    res = run_one(src, uploads, quality=100, keep_larger=True)
    assert res.status == CONVERTED
    assert (uploads / "t.jpg.webp").exists()


def test_stale_output_removed_when_no_longer_smaller(uploads):
    src = tiny_jpeg(uploads / "t.jpg")
    (uploads / "t.jpg.webp").write_bytes(b"stale")
    old = os.stat(src).st_mtime - 100
    os.utime(uploads / "t.jpg.webp", (old, old))
    run_one(src, uploads, quality=100)
    assert not (uploads / "t.jpg.webp").exists()


def test_exif_orientation_applied_and_exif_stripped(uploads):
    img = Image.new("RGB", (300, 100), (10, 200, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    exif[0x010F] = "SecretCam"  # make
    img.save(uploads / "o.jpg", "JPEG", quality=95, exif=exif.tobytes())
    res = run_one(uploads / "o.jpg", uploads, keep_larger=True)
    assert res.status == CONVERTED
    with Image.open(uploads / "o.jpg.webp") as out:
        assert out.size == (100, 300)  # pixels rotated
        assert not out.info.get("exif")


def test_icc_profile_preserved(uploads):
    from PIL import ImageCms

    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    make_photo().save(uploads / "i.jpg", "JPEG", quality=95, icc_profile=profile)
    run_one(uploads / "i.jpg", uploads)
    with Image.open(uploads / "i.jpg.webp") as out:
        assert out.info.get("icc_profile")


def test_resize_keeps_aspect_ratio(uploads):
    src = save_jpeg(uploads / "big.jpg", 1000, 500)
    res = run_one(src, uploads, max_width=400)
    assert res.resized
    with Image.open(src) as im:
        assert im.size == (400, 200)
    with Image.open(uploads / "big.jpg.webp") as im:
        assert im.size == (400, 200)
    assert res.original_bytes > res.source_bytes


def test_resize_never_upscales(uploads):
    src = save_jpeg(uploads / "small.jpg", 200, 100)
    before = src.read_bytes()
    res = run_one(src, uploads, max_width=400)
    assert not res.resized
    assert src.read_bytes() == before


def test_resize_png_stays_png(uploads):
    src = save_png(uploads / "big.png", 900, 300, mode="RGBA")
    run_one(src, uploads, max_width=300)
    with Image.open(src) as im:
        assert im.format == "PNG"
        assert im.size == (300, 100)


def test_resize_backup_created_with_original_bytes(uploads, tmp_path):
    src = save_jpeg(uploads / "x/big.jpg", 800, 400)
    original = src.read_bytes()
    backup = tmp_path / "bk"
    run_one(src, uploads, max_width=200, backup_dir=backup)
    assert (backup / "x/big.jpg").read_bytes() == original


def test_backup_never_overwrites_first_original(uploads, tmp_path):
    src = save_jpeg(uploads / "big.jpg", 800, 400)
    original = src.read_bytes()
    backup = tmp_path / "bk"
    run_one(src, uploads, max_width=400, backup_dir=backup)
    run_one(src, uploads, max_width=100, backup_dir=backup)
    assert (backup / "big.jpg").read_bytes() == original


def test_no_backup_dir_means_no_copy(uploads, tmp_path):
    src = save_jpeg(uploads / "big.jpg", 800, 400)
    run_one(src, uploads, max_width=200)
    assert not (tmp_path / "bk").exists()


def test_idempotent_second_run_skips(uploads):
    src = save_jpeg(uploads / "a.jpg")
    assert run_one(src, uploads).status == CONVERTED
    assert run_one(src, uploads).status == UPTODATE


def test_idempotent_after_resize(uploads):
    src = save_jpeg(uploads / "a.jpg", 900, 300)
    assert run_one(src, uploads, max_width=300).status == CONVERTED
    assert run_one(src, uploads, max_width=300).status == UPTODATE


def test_newer_source_triggers_reconvert(uploads):
    src = save_jpeg(uploads / "a.jpg")
    run_one(src, uploads)
    out = uploads / "a.jpg.webp"
    future = out.stat().st_mtime + 50
    os.utime(src, (future, future))
    assert run_one(src, uploads).status == CONVERTED


def test_force_reconverts(uploads):
    src = save_jpeg(uploads / "a.jpg")
    run_one(src, uploads)
    assert run_one(src, uploads, force=True).status == CONVERTED


def test_missing_output_triggers_reconvert(uploads):
    src = save_jpeg(uploads / "a.jpg")
    run_one(src, uploads)
    (uploads / "a.jpg.webp").unlink()
    assert run_one(src, uploads).status == CONVERTED


def test_fingerprint_mismatch_in_manifest_entry_reconverts(uploads):
    src = save_jpeg(uploads / "a.jpg")
    run_one(src, uploads, quality=80)
    st = src.stat()
    entry = {
        "fingerprint": Options(quality=50).fingerprint(),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }
    assert process_image(src, uploads, Options(quality=80), entry).status == CONVERTED


def test_dry_run_writes_nothing(uploads):
    src = save_jpeg(uploads / "a.jpg", 900, 300)
    before = src.read_bytes()
    res = run_one(src, uploads, dry_run=True, max_width=300)
    assert res.status == WOULD_CONVERT and res.resized
    assert src.read_bytes() == before
    assert not (uploads / "a.jpg.webp").exists()
    assert [p.name for p in uploads.iterdir()] == ["a.jpg"]


def test_corrupt_file_is_error_not_crash(uploads):
    (uploads / "bad.jpg").write_bytes(b"this is not an image")
    res = run_one(uploads / "bad.jpg", uploads)
    assert res.status == ERROR and res.message


def test_no_temp_files_left_behind(uploads):
    src = save_jpeg(uploads / "a.jpg", 800, 400)
    run_one(src, uploads, max_width=300)
    assert not [p for p in uploads.iterdir() if p.name.endswith(".tmp")]


def test_animated_png_skipped(uploads):
    frames = [Image.new("RGB", (40, 40), (i * 40, 0, 0)) for i in range(4)]
    frames[0].save(uploads / "anim.png", save_all=True, append_images=frames[1:], duration=50)
    res = run_one(uploads / "anim.png", uploads)
    assert res.status == ANIMATED
    assert not (uploads / "anim.png.webp").exists()


@needs_avif
def test_avif_output(uploads):
    src = save_jpeg(uploads / "a.jpg")
    res = run_one(src, uploads, avif=True)
    assert "avif" in res.outputs and (uploads / "a.jpg.avif").is_file()


@pytest.mark.parametrize(
    "size,max_w,expected",
    [
        ((1000, 500), 400, (400, 200)),
        ((300, 300), 400, (300, 300)),
        ((1001, 333), 500, (500, 166)),
        ((400, 100), 400, (400, 100)),
        ((5000, 1), 100, (100, 1)),
    ],
)
def test_target_size(size, max_w, expected):
    assert target_size(*size, max_w) == expected


@pytest.mark.parametrize("mode", ["1", "L", "LA", "P", "CMYK", "RGB", "RGBA"])
def test_normalize_mode_returns_rgb_or_rgba(mode):
    img = Image.new(mode, (4, 4))
    assert normalize_mode(img).mode in ("RGB", "RGBA")
