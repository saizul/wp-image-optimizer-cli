from __future__ import annotations

import random
from pathlib import Path

import pytest
from PIL import Image

from wp_imgopt.options import Options


def make_photo(width: int = 320, height: int = 200, seed: int = 1) -> Image.Image:
    """A gradient with mild noise: compresses far better as WebP than as a q95 JPEG."""
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (
                (x * 255 // max(1, width - 1) + rng.randint(0, 6)) % 256,
                (y * 255 // max(1, height - 1)) % 256,
                ((x + y) * 255 // max(1, width + height - 2) + rng.randint(0, 6)) % 256,
            )
    return img


def save_jpeg(path: Path, width: int = 320, height: int = 200, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("quality", 95)
    make_photo(width, height).save(path, "JPEG", **kwargs)
    return path


def save_png(path: Path, width: int = 320, height: int = 200, mode: str = "RGB") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = make_photo(width, height)
    if mode == "RGBA":
        img = img.convert("RGBA")
        img.putalpha(Image.linear_gradient("L").resize((width, height)))
    elif mode != "RGB":
        img = img.convert(mode)
    img.save(path, "PNG")
    return path


@pytest.fixture
def uploads(tmp_path: Path) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    return root


@pytest.fixture
def opts() -> Options:
    return Options(workers=2)


@pytest.fixture
def sample_tree(uploads: Path) -> Path:
    save_jpeg(uploads / "2024/05/photo.jpg")
    save_png(uploads / "2024/05/logo.png", mode="RGBA")
    save_jpeg(uploads / "2024/05/photo-150x150.jpg", 150, 150)
    save_jpeg(uploads / "2024/06/banner.jpeg", 480, 160)
    return uploads
