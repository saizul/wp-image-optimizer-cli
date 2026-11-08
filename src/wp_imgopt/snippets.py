"""Web server snippets that serve WebP/AVIF to browsers that accept them."""

from __future__ import annotations

from wp_imgopt.options import NAMING_APPEND, NAMING_REPLACE


def nginx_snippet(naming: str = NAMING_APPEND, avif: bool = False) -> str:
    """Return nginx config: an ``http`` level map plus a ``server`` level location."""
    none = "" if naming == NAMING_APPEND else ".no-modern-format"
    lines = [
        "# --- http { } level (e.g. /etc/nginx/conf.d/images-map.conf) ---",
    ]
    if avif:
        lines += [
            "map $http_accept $avif_ext {",
            f'    default "{none}";',
            '    "~*image/avif" ".avif";',
            "}",
        ]
    lines += [
        "map $http_accept $webp_ext {",
        f'    default "{none}";',
        '    "~*image/webp" ".webp";',
        "}",
        "",
        "# --- server { } level, before your generic static-file location ---",
    ]
    if naming == NAMING_APPEND:
        lines.append(r"location ~* \.(?:jpe?g|png)$ {")
        base = "$uri"
    else:
        lines.append(r"location ~* ^(?<base>.+)\.(?:jpe?g|png)$ {")
        base = "$base"
    tries = []
    if avif:
        tries.append(f"{base}$avif_ext")
    tries.append(f"{base}$webp_ext")
    lines += [
        "    add_header Vary Accept;",
        "    expires 30d;",
        f"    try_files {' '.join(tries)} $uri =404;",
        "}",
        "",
        "# Make sure the types are known (usually already in mime.types):",
        "#   image/webp  webp;",
        "#   image/avif  avif;",
        "# Note: add_header inside a location replaces headers inherited from the",
        "# server block, so repeat any security headers you rely on here.",
    ]
    return "\n".join(lines) + "\n"


def htaccess_snippet(naming: str = NAMING_APPEND, avif: bool = False) -> str:
    """Return an .htaccess block for Apache (mod_rewrite, mod_headers, mod_mime)."""
    lines = [
        "# BEGIN wp-imgopt",
        "<IfModule mod_mime.c>",
        "  AddType image/webp .webp",
    ]
    if avif:
        lines.append("  AddType image/avif .avif")
    lines += ["</IfModule>", "", "<IfModule mod_rewrite.c>", "  RewriteEngine On"]

    def block(fmt: str, mime: str) -> list[str]:
        if naming == NAMING_APPEND:
            return [
                f"  RewriteCond %{{HTTP_ACCEPT}} {mime}",
                "  RewriteCond %{REQUEST_FILENAME} -f",
                f"  RewriteCond %{{REQUEST_FILENAME}}.{fmt} -f",
                f"  RewriteRule ^(.+)\\.(jpe?g|png)$ $1.$2.{fmt} [T={mime},L]",
            ]
        assert naming == NAMING_REPLACE
        return [
            f"  RewriteCond %{{HTTP_ACCEPT}} {mime}",
            "  RewriteCond %{REQUEST_FILENAME} ^(.+)\\.(jpe?g|png)$",
            f"  RewriteCond %1.{fmt} -f",
            f"  RewriteRule ^(.+)\\.(jpe?g|png)$ $1.{fmt} [T={mime},L]",
        ]

    if avif:
        lines += block("avif", "image/avif") + [""]
    lines += block("webp", "image/webp")
    lines += [
        "</IfModule>",
        "",
        "<IfModule mod_headers.c>",
        '  <FilesMatch "\\.(jpe?g|png)$">',
        "    Header append Vary Accept",
        "  </FilesMatch>",
        "</IfModule>",
        "# END wp-imgopt",
    ]
    return "\n".join(lines) + "\n"
