from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from conftest import save_jpeg
from wp_imgopt.cli import main
from wp_imgopt.options import NAMING_REPLACE
from wp_imgopt.orphans import (
    ORPHAN,
    STALE_TEMP,
    UNVERIFIED,
    delete_orphans,
    find_orphans,
)


def touch(path: Path, data: bytes = b"x" * 10, age: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if age:
        old = time.time() - age
        os.utime(path, (old, old))
    return path


@pytest.fixture
def messy(uploads: Path) -> Path:
    save_jpeg(uploads / "2024/05/kept.jpg")
    touch(uploads / "2024/05/kept.jpg.webp")
    touch(uploads / "2024/05/kept.jpg.avif")
    touch(uploads / "2024/05/gone.jpg.webp", b"y" * 25)
    touch(uploads / "2024/05/gone.jpg.avif", b"y" * 5)
    touch(uploads / "2024/05/gone-150x150.jpg.webp")
    touch(uploads / "2024/05/upload.webp")  # a WebP the editor uploaded on purpose
    touch(uploads / "2024/05/.gone.jpg.webp.123.456.tmp", age=7200)
    touch(uploads / "2024/05/.fresh.jpg.webp.123.457.tmp")
    touch(uploads / ".hidden/zombie.jpg.webp")
    return uploads


def kinds(report) -> dict[str, str]:
    return {o.rel: o.kind for o in report.items}


def test_append_naming_finds_real_orphans_only(messy):
    report = find_orphans(messy)
    assert kinds(report) == {
        "2024/05/gone.jpg.webp": ORPHAN,
        "2024/05/gone.jpg.avif": ORPHAN,
        "2024/05/gone-150x150.jpg.webp": ORPHAN,
        "2024/05/.gone.jpg.webp.123.456.tmp": STALE_TEMP,
    }
    gone = next(o for o in report.items if o.rel == "2024/05/gone.jpg.webp")
    assert gone.expected_source == "2024/05/gone.jpg"
    assert report.reclaimable_bytes == 25 + 5 + 10 + 10


def test_fresh_temp_is_reported_when_min_age_is_zero(messy):
    report = find_orphans(messy, temp_min_age=0)
    assert "2024/05/.fresh.jpg.webp.123.457.tmp" in kinds(report)


def test_uppercase_and_png_sources(uploads):
    save_jpeg(uploads / "a/Photo.JPG")
    touch(uploads / "a/Photo.JPG.webp")
    touch(uploads / "a/Logo.PNG.webp")
    assert kinds(find_orphans(uploads)) == {"a/Logo.PNG.webp": ORPHAN}


def test_exclude_and_backup_dir_are_skipped(messy):
    touch(messy / "backup/old.jpg.webp")
    report = find_orphans(messy, exclude=("gone-*",), backup_dir=messy / "backup")
    assert "2024/05/gone-150x150.jpg.webp" not in kinds(report)
    assert "backup/old.jpg.webp" not in kinds(report)


def test_replace_naming_marks_unverified(uploads):
    save_jpeg(uploads / "x/has-source.jpg")
    touch(uploads / "x/has-source.webp")
    save_jpeg(uploads / "x/upper.JPEG")
    touch(uploads / "x/upper.webp")
    touch(uploads / "x/lonely.webp")
    touch(uploads / "x/lonely.avif")
    touch(uploads / "x/append-style.jpg.webp")
    report = find_orphans(uploads, NAMING_REPLACE)
    assert kinds(report) == {"x/lonely.avif": UNVERIFIED, "x/lonely.webp": UNVERIFIED}
    assert report.reclaimable_bytes == 0


def test_delete_removes_only_deletable(messy):
    report = delete_orphans(messy, find_orphans(messy))
    assert sorted(report.deleted) == sorted(
        [
            "2024/05/gone.jpg.webp",
            "2024/05/gone.jpg.avif",
            "2024/05/gone-150x150.jpg.webp",
            "2024/05/.gone.jpg.webp.123.456.tmp",
        ]
    )
    assert (messy / "2024/05/kept.jpg.webp").exists()
    assert (messy / "2024/05/upload.webp").exists()
    assert (messy / "2024/05/.fresh.jpg.webp.123.457.tmp").exists()
    assert find_orphans(messy).items == []


def test_delete_never_touches_unverified(uploads):
    touch(uploads / "lonely.webp")
    report = delete_orphans(uploads, find_orphans(uploads, NAMING_REPLACE))
    assert report.deleted == [] and (uploads / "lonely.webp").exists()


def test_missing_root_and_bad_age(tmp_path):
    with pytest.raises(NotADirectoryError):
        find_orphans(tmp_path / "nope")
    with pytest.raises(ValueError):
        find_orphans(tmp_path, temp_min_age=-1)


# ---- CLI ------------------------------------------------------------------------


def test_cli_lists_without_deleting(messy, capsys):
    assert main([str(messy), "--find-orphans"]) == 0
    out = capsys.readouterr().out
    assert "gone.jpg.webp" in out and "re-run with --delete" in out
    assert (messy / "2024/05/gone.jpg.webp").exists()


def test_cli_delete(messy, capsys):
    assert main([str(messy), "--find-orphans", "--delete"]) == 0
    assert "(deleted)" in capsys.readouterr().out
    assert not (messy / "2024/05/gone.jpg.webp").exists()
    assert (messy / "2024/05/kept.jpg.webp").exists()


def test_cli_dry_run_overrides_delete(messy):
    assert main([str(messy), "--find-orphans", "--delete", "-n", "--quiet"]) == 0
    assert (messy / "2024/05/gone.jpg.webp").exists()


def test_cli_json_report(messy, tmp_path):
    report = tmp_path / "nested/orphans.json"
    assert main([str(messy), "--find-orphans", "--quiet", "--json-report", str(report)]) == 0
    data = json.loads(report.read_text())
    assert data["orphans"] == 3 and data["stale_temp"] == 1 and data["unverified"] == 0
    assert data["deleted"] == []


def test_cli_replace_naming_warns(uploads, capsys):
    touch(uploads / "lonely.webp")
    assert main([str(uploads), "--find-orphans", "--naming", "replace", "--delete"]) == 0
    out = capsys.readouterr().out
    assert "never deleted automatically" in out
    assert (uploads / "lonely.webp").exists()


def test_cli_delete_requires_find_orphans(uploads):
    with pytest.raises(SystemExit) as exc:
        main([str(uploads), "--delete"])
    assert exc.value.code == 2


def test_cli_rejects_sql_replace_combo(uploads):
    with pytest.raises(SystemExit) as exc:
        main([str(uploads), "--find-orphans", "--sql-replace", "--site-url", "https://e.com"])
    assert exc.value.code == 2


def test_cli_bad_root_and_negative_age(tmp_path, uploads):
    assert main([str(tmp_path / "missing"), "--find-orphans"]) == 2
    assert main([str(uploads), "--find-orphans", "--temp-min-age", "-5"]) == 2


def test_cli_reports_delete_failure(messy, monkeypatch, capsys):
    real_unlink = Path.unlink

    def flaky(self, *a, **kw):
        if self.name == "gone.jpg.avif":
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", flaky)
    assert main([str(messy), "--find-orphans", "--delete", "--quiet"]) == 1
    assert "could not delete 2024/05/gone.jpg.avif" in capsys.readouterr().err
