from __future__ import annotations

import json

import pytest

from conftest import save_jpeg
from wp_imgopt import __version__
from wp_imgopt.cli import build_parser, main, options_from_args


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_nginx_prints_snippet(capsys):
    assert main(["--nginx"]) == 0
    assert "try_files" in capsys.readouterr().out


def test_htaccess_prints_snippet(capsys):
    assert main(["--htaccess", "--naming", "replace"]) == 0
    assert "RewriteRule" in capsys.readouterr().out


def test_both_snippets(capsys):
    main(["--nginx", "--htaccess"])
    out = capsys.readouterr().out
    assert "try_files" in out and "BEGIN wp-imgopt" in out


def test_root_required(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_end_to_end_run(sample_tree, capsys):
    assert main([str(sample_tree), "--quiet", "-j", "2"]) == 0
    assert (sample_tree / "2024/05/photo.jpg.webp").is_file()


def test_summary_table_printed(sample_tree, capsys):
    main([str(sample_tree), "-j", "1"])
    out = capsys.readouterr().out
    assert "Files scanned" in out and "Saved" in out


def test_json_report(sample_tree, tmp_path):
    report = tmp_path / "r.json"
    main([str(sample_tree), "--quiet", "--json-report", str(report)])
    data = json.loads(report.read_text())
    assert data["converted"] == 3 and data["bytes_saved"] > 0


def test_dry_run_flag(sample_tree):
    main([str(sample_tree), "--quiet", "-n"])
    assert not list(sample_tree.rglob("*.webp"))


def test_exit_code_1_on_errors(uploads):
    (uploads / "bad.jpg").write_bytes(b"x")
    assert main([str(uploads), "--quiet"]) == 1


def test_exit_code_2_missing_dir(tmp_path):
    assert main([str(tmp_path / "nope"), "--quiet"]) == 2


def test_invalid_quality_exits_2(uploads):
    with pytest.raises(SystemExit) as exc:
        main([str(uploads), "--quality", "500"])
    assert exc.value.code == 2


def test_options_from_args_maps_flags(tmp_path):
    args = build_parser().parse_args(
        [
            str(tmp_path),
            "-q",
            "70",
            "--max-width",
            "1600",
            "--backup-dir",
            str(tmp_path / "b"),
            "--include-generated",
            "--no-manifest",
            "--exclude",
            "x/*",
            "-j",
            "8",
            "--naming",
            "replace",
        ]
    )
    o = options_from_args(args)
    assert (o.quality, o.max_width, o.workers, o.naming) == (70, 1600, 8, "replace")
    assert o.include_generated and not o.use_manifest and o.exclude == ("x/*",)


def test_sql_replace_requires_site_url(uploads):
    with pytest.raises(SystemExit) as exc:
        main([str(uploads), "--sql-replace"])
    assert exc.value.code == 2


def test_sql_replace_output(sample_tree, capsys):
    main([str(sample_tree), "--quiet"])
    capsys.readouterr()
    code = main(
        [
            str(sample_tree),
            "--sql-replace",
            "--site-url",
            "https://example.com",
            "--elementor",
            "--only",
            "2024/05/*",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "wp search-replace" in out and "--dry-run" in out
    assert "banner" not in out and "photo.jpg.webp" in out


def test_sql_replace_with_url_list(sample_tree, capsys, tmp_path):
    main([str(sample_tree), "--quiet"])
    capsys.readouterr()
    lst = tmp_path / "urls.txt"
    lst.write_text("https://example.com/wp-content/uploads/2024/06/banner.jpeg\n")
    assert (
        main(
            [
                str(sample_tree),
                "--sql-replace",
                "--site-url",
                "https://example.com",
                "--url-list",
                str(lst),
            ]
        )
        == 0
    )
    assert "banner.jpeg.webp" in capsys.readouterr().out


def test_sql_replace_nothing_to_do(uploads, capsys):
    save_jpeg(uploads / "a.jpg")
    assert main([str(uploads), "--sql-replace", "--site-url", "https://e.com"]) == 1


def test_json_report_creates_missing_folders(sample_tree, tmp_path):
    report = tmp_path / "reports" / "nested" / "r.json"
    assert main([str(sample_tree), "--quiet", "--json-report", str(report)]) == 0
    assert json.loads(report.read_text())["converted"] == 3


def test_json_report_unwritable_path_fails_before_processing(sample_tree, tmp_path, capsys):
    target = tmp_path / "a-directory"
    target.mkdir()
    assert main([str(sample_tree), "--quiet", "--json-report", str(target)]) == 2
    assert "cannot write --json-report" in capsys.readouterr().err
    assert not list(sample_tree.rglob("*.webp"))  # nothing was converted


def test_json_report_parent_is_a_file(sample_tree, tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    assert main([str(sample_tree), "--quiet", "--json-report", str(blocker / "r.json")]) == 2
    assert not list(sample_tree.rglob("*.webp"))


def test_failed_run_leaves_no_probe_file(tmp_path):
    report = tmp_path / "r.json"
    assert main([str(tmp_path / "nope"), "--quiet", "--json-report", str(report)]) == 2
    assert not report.exists()
