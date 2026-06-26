#!/usr/bin/env python3
"""
sitemap-generator.py
====================

Scans every HTML file under the site root and rebuilds sitemap.xml from
scratch with the correct priorities and changefreq values.

Priority rules:
    homepage                    = 1.0
    reviews/*, comparisons/*    = 0.9
    articles/*                  = 0.8
    section index pages         = 0.7
    about, contact, supporting  = 0.5

Changefreq rules:
    homepage                    = weekly
    articles, comparisons, reviews = monthly
    everything else             = monthly

Usage:
    python3 sitemap-generator.py
    python3 sitemap-generator.py --domain emailtooladviser.com
    python3 sitemap-generator.py --root /path/to/site
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT_DEFAULT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"

EXCLUDE_DIRS = {".git", "automation", "data", "reports", "dashboard", "docs", ".github"}
EXCLUDE_FILES = {"og-default.html"}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            return json.load(f)
    return {"core_domain": "emailtooladviser.com"}


def lastmod_for(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def classify(rel_url: str) -> tuple[str, str]:
    """Return (priority, changefreq) for a relative URL beginning with '/'."""
    if rel_url == "/":
        return ("1.0", "weekly")
    if rel_url.startswith("/reviews/") and rel_url not in ("/reviews/",):
        return ("0.9", "monthly")
    if rel_url.startswith("/comparisons/") and rel_url not in ("/comparisons/",):
        return ("0.9", "monthly")
    if rel_url.startswith("/articles/") and rel_url not in ("/articles/",):
        return ("0.8", "monthly")
    if rel_url in ("/articles/", "/comparisons/", "/reviews/"):
        return ("0.7", "weekly")
    return ("0.5", "monthly")


def collect_pages(site_root: Path) -> list[tuple[str, Path]]:
    """Return a list of (relative_url, source_path) tuples for every HTML page."""
    pages: list[tuple[str, Path]] = []
    for path in site_root.rglob("*.html"):
        # Skip excluded directories.
        parts = path.relative_to(site_root).parts
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        rel = path.relative_to(site_root).as_posix()
        if rel == "index.html":
            rel_url = "/"
        elif rel.endswith("/index.html"):
            rel_url = "/" + rel[:-len("index.html")]
        else:
            rel_url = "/" + rel
        pages.append((rel_url, path))
    # Sort: homepage first, then by URL.
    pages.sort(key=lambda x: (0 if x[0] == "/" else 1, x[0]))
    return pages


def build_sitemap(domain: str, pages: list[tuple[str, Path]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    base = f"https://{domain}"
    for rel_url, path in pages:
        prio, freq = classify(rel_url)
        loc = escape(base + rel_url)
        lm = lastmod_for(path)
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{lm}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{prio}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Rebuild sitemap.xml from disk.")
    parser.add_argument("--root", default=str(SITE_ROOT_DEFAULT),
                        help="Site root directory.")
    parser.add_argument("--domain", default=cfg.get("core_domain", "emailtooladviser.com"),
                        help="Production domain (no protocol).")
    parser.add_argument("--out", default=None,
                        help="Output path; defaults to <root>/sitemap.xml.")
    args = parser.parse_args()

    site_root = Path(args.root).resolve()
    out_path = Path(args.out).resolve() if args.out else site_root / "sitemap.xml"

    pages = collect_pages(site_root)
    if not pages:
        print(f"No HTML files found under {site_root}. Nothing to write.", file=sys.stderr)
        sys.exit(1)

    sitemap = build_sitemap(args.domain, pages)
    out_path.write_text(sitemap, encoding="utf-8")
    print(f"Wrote {len(pages)} URLs to {out_path}")


if __name__ == "__main__":
    main()
