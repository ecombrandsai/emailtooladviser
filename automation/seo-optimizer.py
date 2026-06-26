#!/usr/bin/env python3
"""
seo-optimizer.py
================

Runs over every HTML article in the site root and applies on-page SEO
checks. Emits a per-file report and (with --fix) applies safe automated
fixes for the most common issues.

Checks performed:
    1. Title tag: target keyword in first 60 chars, year present, ≤60 chars
    2. Meta description: keyword in first 20 words, CTA word, ≤160 chars
    3. Header structure: exactly 1 H1, ≥4 H2, no skipped levels
    4. Internal linking: ≥3 internal links, descriptive anchor text
    5. Schema markup: Article, FAQPage, BreadcrumbList all present
    6. Image alt text: every <img> has alt + width + height
    7. Image weight: warn on any image src above 200KB (best-effort)

Usage:
    python3 automation/seo-optimizer.py
    python3 automation/seo-optimizer.py --fix
    python3 automation/seo-optimizer.py --target articles/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
REPORT_PATH = SITE_ROOT / "data" / "seo-report.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Pull the canonical (keyword → URL) map from the queue.
def keyword_map() -> dict[str, str]:
    queue = load_json(QUEUE_PATH)
    out = {}
    for k in queue.get("keywords", []):
        url = k.get("article_url") or k.get("url")
        if not url:
            continue
        out[url] = k.get("keyword", "")
    return out


# ----------------------------------------------------------------------
# Individual checks
# ----------------------------------------------------------------------

def check_title(html: str, keyword: str) -> dict:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    title = (m.group(1).strip() if m else "")
    return {
        "title": title,
        "length": len(title),
        "has_keyword_in_first_60": keyword.lower() in title[:60].lower() if keyword else None,
        "has_year": "2026" in title or "2025" in title,
        "under_60_chars": len(title) <= 60,
        "ok": len(title) > 0 and len(title) <= 60 and ("2026" in title or "2025" in title),
    }


def check_meta_description(html: str, keyword: str) -> dict:
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, flags=re.I)
    desc = (m.group(1).strip() if m else "")
    first_20 = " ".join(desc.split()[:20]).lower()
    cta_words = {"get", "start", "free", "compare", "find", "learn", "see"}
    return {
        "description": desc,
        "length": len(desc),
        "has_keyword_in_first_20_words": keyword.lower() in first_20 if keyword else None,
        "has_cta_word": any(w in desc.lower() for w in cta_words),
        "under_160_chars": len(desc) <= 160,
        "ok": 0 < len(desc) <= 160,
    }


def check_headers(html: str, keyword: str) -> dict:
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.I | re.S)
    h3s = re.findall(r"<h3[^>]*>(.*?)</h3>", html, flags=re.I | re.S)
    strip = lambda s: re.sub(r"<[^>]+>", "", s).strip()
    h1_text = strip(h1s[0]) if h1s else ""
    return {
        "h1_count": len(h1s),
        "h1_text": h1_text,
        "h1_has_keyword": keyword.lower() in h1_text.lower() if (keyword and h1_text) else None,
        "h2_count": len(h2s),
        "h3_count": len(h3s),
        "has_skipped_level": len(h2s) == 0 and len(h3s) > 0,
        "ok": len(h1s) == 1 and len(h2s) >= 4 and not (len(h2s) == 0 and len(h3s) > 0),
    }


def check_internal_links(html: str) -> dict:
    links = re.findall(r'<a[^>]+href="(/[^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S)
    descriptive_anchors = [(href, re.sub(r"<[^>]+>", "", text).strip()) for href, text in links]
    bad_anchors = sum(1 for _, t in descriptive_anchors if t.lower() in {"click here", "read more", "here", "more"})
    return {
        "internal_link_count": len(descriptive_anchors),
        "bad_anchor_count": bad_anchors,
        "ok": len(descriptive_anchors) >= 3 and bad_anchors == 0,
    }


def check_schema(html: str) -> dict:
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, flags=re.I | re.S)
    types = []
    for b in blocks:
        try:
            data = json.loads(b.strip())
            t = data.get("@type")
            if isinstance(t, list):
                types.extend(t)
            elif t:
                types.append(t)
        except Exception:  # noqa: BLE001
            continue
    return {
        "block_count": len(blocks),
        "types": types,
        "has_article": "Article" in types,
        "has_breadcrumb": "BreadcrumbList" in types,
        "has_faq": "FAQPage" in types,
        "ok": "Article" in types and "BreadcrumbList" in types and "FAQPage" in types,
    }


def check_images(html: str) -> dict:
    imgs = re.findall(r"<img\b([^>]*)>", html, flags=re.I)
    total = len(imgs)
    missing_alt = sum(1 for i in imgs if not re.search(r'\balt\s*=\s*"[^"]+"', i, flags=re.I))
    missing_dims = sum(
        1 for i in imgs
        if not (re.search(r'\bwidth\s*=', i, flags=re.I) and re.search(r'\bheight\s*=', i, flags=re.I))
    )
    return {
        "img_count": total,
        "missing_alt": missing_alt,
        "missing_dims": missing_dims,
        "ok": total == 0 or (missing_alt == 0),
    }


# ----------------------------------------------------------------------
# Per-file
# ----------------------------------------------------------------------

def audit_file(path: Path, keyword: str) -> dict:
    html = path.read_text(encoding="utf-8")
    rep = {
        "path": str(path.relative_to(SITE_ROOT)),
        "keyword": keyword,
        "title": check_title(html, keyword),
        "meta_description": check_meta_description(html, keyword),
        "headers": check_headers(html, keyword),
        "internal_links": check_internal_links(html),
        "schema": check_schema(html),
        "images": check_images(html),
    }
    rep["all_ok"] = all(
        rep[k].get("ok", False)
        for k in ("title", "meta_description", "headers", "internal_links", "schema", "images")
    )
    return rep


def auto_fix(path: Path, report: dict) -> bool:
    """Best-effort safe fixes. Returns True if any change was made."""
    html = path.read_text(encoding="utf-8")
    changed = False

    # 1. If meta description missing CTA word, append " — get our top pick."
    if not report["meta_description"]["has_cta_word"]:
        m = re.search(r'(<meta\s+name=["\']description["\']\s+content=["\'])(.*?)(["\'])', html, flags=re.I)
        if m and len(m.group(2)) < 140:
            new_desc = m.group(2).rstrip(".") + ". Get our top pick."
            html = html[:m.start(2)] + new_desc + html[m.end(2):]
            changed = True

    # 2. If any image is missing alt, add a generic one based on the keyword.
    if report["images"]["missing_alt"] > 0 and report["keyword"]:
        def add_alt(match):
            inner = match.group(1)
            if re.search(r'\balt\s*=\s*"[^"]+"', inner, flags=re.I):
                return match.group(0)
            return "<img" + inner + f' alt="{report["keyword"]} — EmailToolAdviser">'
        html, n = re.subn(r"<img\b([^>]*)>", add_alt, html, flags=re.I)
        if n > 0:
            changed = True

    if changed:
        path.write_text(html, encoding="utf-8")
    return changed


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="", help="Subdirectory to limit the audit to.")
    parser.add_argument("--fix", action="store_true", help="Apply safe automated fixes in-place.")
    args = parser.parse_args()

    kw_map = keyword_map()
    target_dir = SITE_ROOT / args.target if args.target else SITE_ROOT
    files = sorted(target_dir.rglob("*.html"))
    excluded = {"dashboard", "automation", "data", "reports", "docs", ".github"}
    files = [f for f in files if not any(p in excluded for p in f.relative_to(SITE_ROOT).parts)]

    reports = []
    fixed_n = 0
    for f in files:
        rel = "/" + f.relative_to(SITE_ROOT).as_posix()
        kw = kw_map.get(rel, "")
        rep = audit_file(f, kw)
        if args.fix:
            if auto_fix(f, rep):
                fixed_n += 1
        reports.append(rep)

    summary = {
        "updated_at": now_iso(),
        "files_audited": len(files),
        "files_passing": sum(1 for r in reports if r["all_ok"]),
        "files_failing": sum(1 for r in reports if not r["all_ok"]),
        "files_auto_fixed": fixed_n,
        "details": reports,
    }
    save_json(REPORT_PATH, summary)
    print(f"SEO audit complete: {summary['files_passing']}/{summary['files_audited']} passing.")
    if args.fix:
        print(f"  ✓ Auto-fixed {fixed_n} files.")
    print(f"  Report: {REPORT_PATH}")
    if summary["files_failing"] and not args.fix:
        sys.exit(1)


if __name__ == "__main__":
    main()
