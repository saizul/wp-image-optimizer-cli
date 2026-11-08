from __future__ import annotations

import pytest

from wp_imgopt.snippets import htaccess_snippet, nginx_snippet


def test_nginx_append_default():
    s = nginx_snippet()
    assert "map $http_accept $webp_ext" in s
    assert "try_files $uri$webp_ext $uri =404;" in s
    assert "Vary Accept" in s
    assert "avif" not in s.split("# Make sure")[0]


def test_nginx_avif_prefers_avif_first():
    s = nginx_snippet(avif=True)
    assert "try_files $uri$avif_ext $uri$webp_ext $uri =404;" in s


def test_nginx_replace_naming():
    s = nginx_snippet("replace")
    assert "(?<base>.+)" in s
    assert "try_files $base$webp_ext $uri =404;" in s
    assert "no-modern-format" in s


def test_nginx_braces_balanced():
    for kwargs in ({}, {"avif": True}, {"naming": "replace"}):
        s = nginx_snippet(**kwargs)
        assert s.count("{") == s.count("}")


def test_htaccess_append():
    s = htaccess_snippet()
    assert "RewriteCond %{HTTP_ACCEPT} image/webp" in s
    assert "RewriteCond %{REQUEST_FILENAME}.webp -f" in s
    assert "$1.$2.webp [T=image/webp,L]" in s
    assert "Header append Vary Accept" in s
    assert s.startswith("# BEGIN wp-imgopt") and s.strip().endswith("# END wp-imgopt")


def test_htaccess_replace():
    s = htaccess_snippet("replace")
    assert "RewriteCond %1.webp -f" in s
    assert "$1.webp [T=image/webp,L]" in s


def test_htaccess_avif_block_before_webp():
    s = htaccess_snippet(avif=True)
    assert s.index("image/avif") < s.index("$1.$2.webp")
    assert "AddType image/avif .avif" in s


@pytest.mark.parametrize("fn", [nginx_snippet, htaccess_snippet])
def test_snippets_end_with_newline(fn):
    assert fn().endswith("\n")
