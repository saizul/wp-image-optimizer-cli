from __future__ import annotations

import shlex

import pytest

from conftest import save_jpeg
from wp_imgopt.optimizer import run
from wp_imgopt.options import Options
from wp_imgopt.sqlreplace import Replacement, collect, render, uploads_base_url

SITE = "https://example.com"


@pytest.fixture
def converted(sample_tree):
    run(sample_tree, Options(include_generated=False))
    return sample_tree


def test_uploads_base_url_normalizes_slashes():
    assert uploads_base_url("https://x.com/", "/wp-content/uploads/") == (
        "https://x.com/wp-content/uploads"
    )


def test_collect_only_converted_files(converted):
    reps, warnings = collect(converted, SITE)
    olds = [r.old for r in reps]
    assert f"{SITE}/wp-content/uploads/2024/05/photo.jpg" in olds
    assert all(not o.endswith("150x150.jpg") for o in olds)
    assert not warnings or all("no .webp" in w for w in warnings)


def test_collect_new_url_uses_naming(converted):
    reps, _ = collect(converted, SITE)
    rep = next(r for r in reps if r.old.endswith("photo.jpg"))
    assert rep.new == rep.old + ".webp"


def test_collect_replace_naming(sample_tree):
    run(sample_tree, Options(naming="replace"))
    reps, _ = collect(sample_tree, SITE, naming="replace")
    rep = next(r for r in reps if r.old.endswith("photo.jpg"))
    assert rep.new.endswith("2024/05/photo.webp")


def test_collect_only_filter(converted):
    reps, _ = collect(converted, SITE, only=("2024/06/*",))
    assert len(reps) == 1 and reps[0].old.endswith("banner.jpeg")


def test_collect_from_url_list(converted):
    entries = [
        f"{SITE}/wp-content/uploads/2024/05/photo.jpg?ver=2",
        "2024/06/banner.jpeg",
        "# comment",
        "",
        "https://other.com/wp-content/uploads/x.jpg",
        "2024/05/notes.txt",
    ]
    reps, warnings = collect(converted, SITE, entries=entries)
    assert len(reps) == 2
    assert any("other.com" in w for w in warnings)
    assert any("notes.txt" in w for w in warnings)


def test_collect_skips_missing_webp(uploads):
    save_jpeg(uploads / "a.jpg")
    reps, warnings = collect(uploads, SITE)
    assert reps == [] and "no .webp" in warnings[0]


def test_collect_dedupes_url_list(converted):
    reps, _ = collect(converted, SITE, entries=["2024/06/banner.jpeg"] * 3)
    assert len(reps) == 1


def test_render_structure_and_order():
    lines = render([Replacement("https://e.com/a.jpg", "https://e.com/a.jpg.webp")])
    text = "\n".join(lines)
    assert text.index("wp db export") < text.index("--dry-run") < text.rindex("wp search-replace")
    assert "--skip-columns=guid" in text and "--precise" in text
    assert "wp cache flush" in text
    assert "elementor flush-css" not in text


def test_render_dry_run_precedes_apply():
    lines = render([Replacement("a", "b")])
    cmds = [ln for ln in lines if ln.startswith("wp search-replace")]
    assert cmds[0].endswith("--dry-run") and not cmds[1].endswith("--dry-run")


def test_render_elementor_adds_escaped_variants():
    lines = render([Replacement("https://e.com/a.jpg", "https://e.com/a.jpg.webp")], elementor=True)
    joined = "\n".join(lines)
    assert "https:\\/\\/e.com\\/a.jpg" in joined
    assert "wp elementor flush-css" in joined
    cmds = [ln for ln in lines if ln.startswith("wp search-replace") and "--dry-run" in ln]
    assert len(cmds) == 2


def test_render_commands_are_shell_safe():
    rep = Replacement("https://e.com/my photo's.jpg", "https://e.com/my photo's.jpg.webp")
    cmd = next(ln for ln in render([rep]) if ln.startswith("wp search-replace"))
    argv = shlex.split(cmd)
    assert argv[2] == rep.old and argv[3] == rep.new


def test_render_wp_path():
    lines = render([Replacement("a", "b")], wp_path="/var/www/my site")
    cmd = next(ln for ln in lines if ln.startswith("wp search-replace"))
    assert "--path=/var/www/my site" in shlex.split(cmd)
