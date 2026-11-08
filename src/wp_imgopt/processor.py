"""Convert a single image: orientation, resize, WebP/AVIF encode."""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from wp_imgopt.options import Options
from wp_imgopt.scanner import output_path

try:  # optional AVIF support
    import pillow_avif  # noqa: F401
except ImportError:  # pragma: no cover - depends on environment
    pass

CONVERTED = "converted"
UPTODATE = "uptodate"
LARGER = "larger"
ANIMATED = "animated"
ERROR = "error"
WOULD_CONVERT = "would_convert"


def avif_available() -> bool:
    """True if Pillow (11.3+ built-in) or pillow-avif-plugin can write AVIF."""
    Image.init()
    return "AVIF" in Image.SAVE


@dataclass
class Result:
    rel: str
    status: str
    original_bytes: int = 0
    source_bytes: int = 0
    outputs: dict[str, int] = field(default_factory=dict)
    skipped_formats: list[str] = field(default_factory=list)
    resized: bool = False
    message: str = ""
    mtime_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.rel,
            "status": self.status,
            "original_bytes": self.original_bytes,
            "source_bytes": self.source_bytes,
            "outputs": self.outputs,
            "resized": self.resized,
            "message": self.message,
        }


def normalize_mode(img: Image.Image) -> Image.Image:
    """Return an RGB or RGBA image that every encoder accepts."""
    mode = img.mode
    if mode in ("RGB", "RGBA"):
        return img
    if mode == "P":
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    if mode in ("LA", "PA"):
        return img.convert("RGBA")
    if mode in ("I;16", "I;16L", "I;16B", "I"):
        return img.point(lambda v: v * (1 / 256)).convert("L").convert("RGB")
    return img.convert("RGB")


def target_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    """Scale down to ``max_width`` keeping the aspect ratio. Never upscales."""
    if width <= max_width:
        return width, height
    return max_width, max(1, round(height * max_width / width))


def _tmp_name(dest: Path) -> Path:
    return dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def _encode(img: Image.Image, dest: Path, fmt: str, **kwargs: Any) -> int:
    """Save to a temp file next to ``dest`` and return its size (not yet committed)."""
    tmp = _tmp_name(dest)
    try:
        img.save(tmp, format=fmt, **kwargs)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp.stat().st_size


def _commit(dest: Path) -> None:
    os.replace(_tmp_name(dest), dest)


def _discard(dest: Path) -> None:
    _tmp_name(dest).unlink(missing_ok=True)


def is_up_to_date(
    src: Path, outputs: dict[str, Path], entry: dict[str, Any] | None, options: Options
) -> bool:
    """Idempotency check: every output exists and is newer than the source."""
    if options.force:
        return False
    if entry is not None and entry.get("fingerprint") != options.fingerprint():
        return False
    st = src.stat()
    unchanged = (
        entry is not None
        and entry.get("size") == st.st_size
        and entry.get("mtime_ns") == st.st_mtime_ns
    )
    skipped = set(entry.get("skipped_formats", [])) if unchanged and entry else set()
    for fmt, out in outputs.items():
        if fmt in skipped:
            continue
        try:
            if out.stat().st_mtime_ns < st.st_mtime_ns:
                return False
        except FileNotFoundError:
            return False
    if options.max_width:
        try:
            with Image.open(src) as probe:
                if probe.size[0] > options.max_width:
                    return False
        except Exception:
            return False
    return True


def process_image(
    src: Path, root: Path, options: Options, entry: dict[str, Any] | None = None
) -> Result:
    rel = src.relative_to(root).as_posix()
    result = Result(rel=rel, status=ERROR)
    try:
        return _process(src, root, rel, options, entry, result)
    except Exception as exc:  # one bad file must not abort a bulk run
        result.status = ERROR
        result.message = f"{type(exc).__name__}: {exc}"
        return result


def _process(
    src: Path, root: Path, rel: str, options: Options, entry: dict[str, Any] | None, result: Result
) -> Result:
    st = src.stat()
    result.original_bytes = result.source_bytes = st.st_size
    result.mtime_ns = st.st_mtime_ns
    outputs = {fmt: output_path(src, fmt, options.naming) for fmt in options.formats}

    if is_up_to_date(src, outputs, entry, options):
        result.status = UPTODATE
        return result

    with Image.open(src) as opened:
        if opened.format == "PNG" and getattr(opened, "is_animated", False):
            result.status = ANIMATED
            result.message = "animated PNG left untouched"
            return result
        icc = opened.info.get("icc_profile")
        opened.load()
        width = opened.size[0]
        will_resize = bool(options.max_width and width > options.max_width)
        if options.dry_run:
            result.status = WOULD_CONVERT
            result.resized = will_resize
            return result
        img = normalize_mode(ImageOps.exif_transpose(opened))
        is_jpeg = opened.format == "JPEG"

    if will_resize:
        new_size = target_size(img.size[0], img.size[1], options.max_width or width)
        img = img.resize(new_size, Image.LANCZOS)
        _backup(src, root, options)
        _write_original(img, src, is_jpeg, icc, options)
        st = src.stat()
        result.source_bytes = st.st_size
        result.mtime_ns = st.st_mtime_ns
        result.resized = True

    for fmt, dest in outputs.items():
        kwargs = _encoder_kwargs(fmt, is_jpeg, icc, options)
        size = _encode(img, dest, fmt.upper(), **kwargs)
        if size >= result.source_bytes and not options.keep_larger:
            _discard(dest)
            result.skipped_formats.append(fmt)
            dest.unlink(missing_ok=True)  # drop stale output from an older run
            continue
        _commit(dest)
        result.outputs[fmt] = size

    if not result.outputs and not result.resized:
        result.status = LARGER
        result.message = "converted files would not be smaller"
    else:
        result.status = CONVERTED
    return result


def _encoder_kwargs(fmt: str, is_jpeg: bool, icc: bytes | None, options: Options) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if icc:
        kwargs["icc_profile"] = icc
    if fmt == "webp":
        kwargs["method"] = 6
        if options.lossless_png and not is_jpeg:
            kwargs["lossless"] = True
            kwargs["quality"] = 100
        else:
            kwargs["quality"] = options.quality
    else:
        kwargs["quality"] = options.avif_quality
    return kwargs


def _backup(src: Path, root: Path, options: Options) -> None:
    if options.backup_dir is None:
        return
    target = options.backup_dir / src.relative_to(root)
    if target.exists():  # never overwrite the first (true) original
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)


def _write_original(
    img: Image.Image, src: Path, is_jpeg: bool, icc: bytes | None, options: Options
) -> None:
    kwargs: dict[str, Any] = {"optimize": True}
    if icc:
        kwargs["icc_profile"] = icc
    if is_jpeg:
        kwargs["quality"] = options.jpeg_quality
        out = img.convert("RGB") if img.mode != "RGB" else img
        fmt = "JPEG"
    else:
        out, fmt = img, "PNG"
    _encode(out, src, fmt, **kwargs)
    _commit(src)
