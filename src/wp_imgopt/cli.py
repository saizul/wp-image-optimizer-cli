"""Command line interface for wp-imgopt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from wp_imgopt import __version__, sqlreplace
from wp_imgopt.optimizer import OptimizerError, run
from wp_imgopt.options import NAMING_APPEND, NAMING_REPLACE, Options
from wp_imgopt.report import Summary, human_bytes
from wp_imgopt.snippets import htaccess_snippet, nginx_snippet


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wp-imgopt",
        description="Bulk-optimize a WordPress wp-content/uploads tree (WebP/AVIF, resize).",
    )
    p.add_argument("root", nargs="?", type=Path, help="uploads directory to process")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    enc = p.add_argument_group("encoding")
    enc.add_argument("-q", "--quality", type=int, default=80, help="WebP quality 1-100 (80)")
    enc.add_argument("--avif", action="store_true", help="also write AVIF files")
    enc.add_argument("--avif-quality", type=int, default=60, help="AVIF quality 1-100 (60)")
    enc.add_argument("--lossless-png", action="store_true", help="encode PNG sources losslessly")
    enc.add_argument(
        "--naming",
        choices=[NAMING_APPEND, NAMING_REPLACE],
        default=NAMING_APPEND,
        help="append: a.jpg.webp (default) | replace: a.webp",
    )
    enc.add_argument("--keep-larger", action="store_true", help="keep outputs not smaller")

    rs = p.add_argument_group("resizing originals")
    rs.add_argument("--max-width", type=int, help="shrink originals wider than this (pixels)")
    rs.add_argument("--jpeg-quality", type=int, default=85, help="quality for resized JPEGs (85)")
    rs.add_argument("--backup-dir", type=Path, help="copy originals here before resizing")

    sel = p.add_argument_group("selection")
    sel.add_argument(
        "--include-generated",
        action="store_true",
        help="also process WordPress sizes like photo-150x150.jpg",
    )
    sel.add_argument("--exclude", action="append", default=[], metavar="GLOB")

    run_g = p.add_argument_group("execution")
    run_g.add_argument("-j", "--workers", type=int, default=4, help="parallel workers (4)")
    run_g.add_argument("-n", "--dry-run", action="store_true", help="report only, write nothing")
    run_g.add_argument("--force", action="store_true", help="ignore timestamps and manifest")
    run_g.add_argument("--no-manifest", action="store_true", help="do not read/write the manifest")
    run_g.add_argument("--manifest", type=Path, help="manifest path (default: inside ROOT)")
    run_g.add_argument("--json-report", type=Path, help="write the full report as JSON")
    run_g.add_argument("--quiet", action="store_true", help="no progress or table output")

    srv = p.add_argument_group("server snippets")
    srv.add_argument("--nginx", action="store_true", help="print an nginx snippet and exit")
    srv.add_argument("--htaccess", action="store_true", help="print an .htaccess block and exit")

    sql = p.add_argument_group("WP-CLI search-replace")
    sql.add_argument("--sql-replace", action="store_true", help="print wp search-replace commands")
    sql.add_argument("--site-url", help="site URL, e.g. https://example.com")
    sql.add_argument("--uploads-path", default=sqlreplace.DEFAULT_UPLOADS_PATH)
    sql.add_argument("--only", action="append", default=[], metavar="GLOB", help="limit to paths")
    sql.add_argument("--url-list", type=Path, help="file with URLs/paths to switch (one per line)")
    sql.add_argument("--elementor", action="store_true", help="also emit JSON-escaped variants")
    sql.add_argument("--wp-path", help="value for wp --path=")
    return p


def options_from_args(args: argparse.Namespace) -> Options:
    return Options(
        quality=args.quality,
        avif=args.avif,
        avif_quality=args.avif_quality,
        lossless_png=args.lossless_png,
        max_width=args.max_width,
        jpeg_quality=args.jpeg_quality,
        backup_dir=args.backup_dir,
        include_generated=args.include_generated,
        naming=args.naming,
        workers=args.workers,
        dry_run=args.dry_run,
        force=args.force,
        keep_larger=args.keep_larger,
        use_manifest=not args.no_manifest,
        manifest_path=args.manifest,
        exclude=tuple(args.exclude),
    )


def render_summary(summary: Summary, console: Console) -> None:
    table = Table(title="wp-imgopt summary" + (" (dry run)" if summary.dry_run else ""))
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    d = summary.to_dict()
    rows = [
        ("Files scanned", d["files_scanned"]),
        ("Converted", d["converted"]),
        ("Would convert (dry run)", d["would_convert"]),
        ("Already up to date", d["up_to_date"]),
        ("Not smaller (kept original only)", d["not_smaller"]),
        ("WP generated sizes skipped", d["generated_sizes_skipped"]),
        ("Originals resized", d["resized_originals"]),
        ("Errors", d["errors"]),
        ("Original bytes", human_bytes(d["bytes_before"])),
        ("WebP bytes", human_bytes(d["bytes_webp"])),
    ]
    if d["bytes_avif"]:
        rows.append(("AVIF bytes", human_bytes(d["bytes_avif"])))
    rows.append(("Saved", f"{human_bytes(d['bytes_saved'])} ({d['percent_saved']}%)"))
    for name, value in rows:
        if value or name in ("Files scanned", "Converted"):
            table.add_row(name, str(value))
    console.print(table)
    for err in summary.errors:
        console.print(f"[red]error[/red] {err.rel}: {err.message}", highlight=False)


def _read_entries(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = Console()
    err = Console(stderr=True)

    if args.nginx or args.htaccess:
        if args.nginx:
            sys.stdout.write(nginx_snippet(args.naming, args.avif))
        if args.htaccess:
            if args.nginx:
                sys.stdout.write("\n")
            sys.stdout.write(htaccess_snippet(args.naming, args.avif))
        return 0

    if args.root is None:
        parser.error("ROOT is required (or use --nginx / --htaccess)")

    if args.sql_replace:
        if not args.site_url:
            parser.error("--sql-replace requires --site-url")
        entries = _read_entries(args.url_list) if args.url_list else None
        reps, warnings = sqlreplace.collect(
            args.root,
            args.site_url,
            uploads_path=args.uploads_path,
            naming=args.naming,
            only=tuple(args.only),
            entries=entries,
        )
        for w in warnings:
            sys.stderr.write(f"warning: {w}\n")
        if not reps:
            sys.stderr.write("nothing to replace: no matching files with converted twins\n")
            return 1
        sys.stdout.write(
            "\n".join(sqlreplace.render(reps, elementor=args.elementor, wp_path=args.wp_path))
            + "\n"
        )
        return 0

    options = options_from_args(args)
    try:
        options.validate()
    except ValueError as exc:
        parser.error(str(exc))

    show_progress = not args.quiet and sys.stderr.isatty()
    try:
        if show_progress:
            with Progress(
                TextColumn("[bold]optimizing[/bold]"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeRemainingColumn(),
                console=err,
                transient=True,
            ) as progress:
                task = progress.add_task("", total=None)

                def tick(_res, done, total):
                    progress.update(task, completed=done, total=total)

                summary = run(args.root, options, tick)
        else:
            summary = run(args.root, options)
    except OptimizerError as exc:
        err.print(f"[red]error:[/red] {exc}", highlight=False)
        return 2

    if args.json_report:
        args.json_report.write_text(
            json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
    if not args.quiet:
        render_summary(summary, out)
    return 1 if summary.errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
