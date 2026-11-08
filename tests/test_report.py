from __future__ import annotations

import pytest

from wp_imgopt.processor import CONVERTED, ERROR, Result
from wp_imgopt.report import Summary, human_bytes


@pytest.mark.parametrize(
    "n,text",
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (5 * 1024**2, "5.0 MB"),
        (3 * 1024**3, "3.0 GB"),
    ],
)
def test_human_bytes(n, text):
    assert human_bytes(n) == text


def make_summary():
    s = Summary()
    s.results = [
        Result("a.jpg", CONVERTED, original_bytes=1000, source_bytes=1000, outputs={"webp": 400}),
        Result(
            "b.jpg",
            CONVERTED,
            original_bytes=3000,
            source_bytes=1500,
            outputs={"webp": 600, "avif": 500},
            resized=True,
        ),
        Result("c.jpg", ERROR, message="boom"),
    ]
    return s


def test_totals():
    s = make_summary()
    assert s.bytes_before == 4000
    assert s.bytes_webp == 1000
    assert s.bytes_avif == 500
    assert s.bytes_saved == 3000
    assert s.percent_saved == 75.0
    assert s.resized == 1


def test_empty_summary_has_zero_percent():
    assert Summary().percent_saved == 0.0


def test_to_dict_counts():
    d = make_summary().to_dict()
    assert d["converted"] == 2 and d["errors"] == 1 and d["files_scanned"] == 3
    assert d["files"][2]["message"] == "boom"
