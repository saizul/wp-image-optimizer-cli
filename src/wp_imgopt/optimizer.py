"""Orchestrates scanning, parallel conversion and manifest bookkeeping."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from wp_imgopt.manifest import Manifest
from wp_imgopt.options import MANIFEST_NAME, Options
from wp_imgopt.processor import (
    CONVERTED,
    ERROR,
    LARGER,
    Result,
    avif_available,
    process_image,
)
from wp_imgopt.report import Summary
from wp_imgopt.scanner import find_collisions, scan

ProgressCallback = Callable[[Result, int, int], None]


class OptimizerError(Exception):
    """Raised for configuration problems detected before any file is touched."""


def run(root: Path, options: Options, progress: ProgressCallback | None = None) -> Summary:
    root = Path(root).resolve()
    if not root.is_dir():
        raise OptimizerError(f"not a directory: {root}")
    options.validate()
    if options.avif and not avif_available():
        raise OptimizerError(
            "AVIF requested but no AVIF encoder is available; "
            "install it with: pip install 'wp-image-optimizer-cli[avif]'"
        )

    found = scan(root, options)
    summary = Summary(
        generated_skipped=found.generated_skipped, excluded=found.excluded, dry_run=options.dry_run
    )
    manifest: Manifest | None = None
    if options.use_manifest:
        manifest = Manifest.load(options.manifest_path or root / MANIFEST_NAME)

    collisions = find_collisions(found.candidates, options)
    todo = [p for p in found.candidates if p not in collisions]
    for path in sorted(collisions):
        summary.results.append(
            Result(
                rel=path.relative_to(root).as_posix(),
                status=ERROR,
                message="output name collides with another source; use --naming append",
            )
        )

    def work(path: Path) -> Result:
        entry = manifest.get(path.relative_to(root).as_posix()) if manifest else None
        return process_image(path, root, options, entry)

    total = len(todo)
    done = 0
    if options.workers == 1 or total <= 1:
        outcomes = iter(work(p) for p in todo)
        for res in outcomes:
            done += 1
            summary.results.append(res)
            if progress:
                progress(res, done, total)
    else:
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            futures = [pool.submit(work, p) for p in todo]
            for fut in as_completed(futures):
                res = fut.result()
                done += 1
                summary.results.append(res)
                if progress:
                    progress(res, done, total)

    summary.results.sort(key=lambda r: r.rel)

    if manifest is not None and not options.dry_run:
        for res in summary.results:
            if res.status in (CONVERTED, LARGER):
                manifest.record(
                    res.rel,
                    size=res.source_bytes,
                    mtime_ns=res.mtime_ns,
                    fingerprint=options.fingerprint(),
                    outputs=res.outputs,
                    skipped_formats=res.skipped_formats,
                )
        manifest.prune(root)
        manifest.save()
    return summary
