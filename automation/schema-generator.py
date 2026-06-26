#!/usr/bin/env python3
"""
schema-generator.py
===================

Builds schema.org JSON-LD blocks for every page type the network ships.
Used by:
    - content-generator.py (at write time)
    - seo-optimizer.py     (--fix mode injects missing blocks)
    - one-shot rebuilds    (`python3 schema-generator.py --rebuild`)

Usage:
    python3 automation/schema-generator.py --rebuild
        Re-emit schema blocks across every HTML file.

    from schema_generator import article, review, faq, breadcrumb, howto
        Programmatic access.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
EXCLUDE_DIRS = {"automation", "data", "reports", "docs", ".github", "dashboard"}

ORG = {
    "@type": "Organization",
    "name": "EmailToolAdviser",
    "url": "https://emailtooladviser.com/",
    "logo": {"@type": "ImageObject", "url": "https://emailtooladviser.com/logo.png"},
}
AUTHOR = {"@type": "Organization", "name": "EmailToolAdviser Editorial Team",
          "url": "https://emailtooladviser.com/about.html"}


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------

def article(headline: str, description: str, canonical: str,
            published: str | None = None, modified: str | None = None) -> dict:
    published = published or date.today().isoformat()
    modified = modified or published
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "author": AUTHOR,
        "publisher": ORG,
        "datePublished": published,
        "dateModified": modified,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }


def review(name: str, rating_value: float, review_body: str | None = None,
           best_rating: float = 5) -> dict:
    out = {
        "@context": "https://schema.org",
        "@type": "Review",
        "itemReviewed": {
            "@type": "SoftwareApplication",
            "name": name,
            "applicationCategory": "BusinessApplication",
            "operatingSystem": "Web",
        },
        "author": AUTHOR,
        "reviewRating": {
            "@type": "Rating",
            "ratingValue": str(rating_value),
            "bestRating": str(best_rating),
        },
        "datePublished": date.today().isoformat(),
    }
    if review_body:
        out["reviewBody"] = review_body
    return out


def faq(qs_and_as: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in qs_and_as
        ],
    }


def breadcrumb(items: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
            for i, (name, url) in enumerate(items)
        ],
    }


def howto(name: str, steps: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": name,
        "step": [
            {"@type": "HowToStep", "name": title, "text": text, "position": i + 1}
            for i, (title, text) in enumerate(steps)
        ],
    }


def comparison_itemlist(items: list[tuple[str, float]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "item": review(name, rating),
            }
            for i, (name, rating) in enumerate(items)
        ],
    }


# ----------------------------------------------------------------------
# Extraction from HTML (for rebuild mode)
# ----------------------------------------------------------------------

def extract_h1(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def extract_meta(html: str, key: str = "description") -> str:
    m = re.search(rf'<meta\s+name=["\']{key}["\']\s+content=["\'](.*?)["\']', html, flags=re.I)
    return m.group(1).strip() if m else ""


def extract_canonical(html: str) -> str:
    m = re.search(r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']', html, flags=re.I)
    return m.group(1).strip() if m else ""


def extract_faqs(html: str) -> list[tuple[str, str]]:
    out = []
    for d in re.findall(r"<details[^>]*>([\s\S]*?)</details>", html, flags=re.I):
        sm = re.search(r"<summary[^>]*>(.*?)</summary>", d, flags=re.I | re.S)
        am = re.search(r"<div\s+class=[\"']answer[\"'][^>]*>([\s\S]*?)</div>", d, flags=re.I)
        if sm and am:
            q = re.sub(r"<[^>]+>", "", sm.group(1)).strip()
            a = re.sub(r"<[^>]+>", "", am.group(1)).strip()
            if q and a:
                out.append((q, a))
    return out


def extract_breadcrumb_items(html: str, fallback_url: str) -> list[tuple[str, str]]:
    nav = re.search(r'<nav[^>]+class=["\'][^"\']*breadcrumbs[^"\']*["\'][^>]*>([\s\S]*?)</nav>', html, flags=re.I)
    items: list[tuple[str, str]] = [("Home", "https://emailtooladviser.com/")]
    if nav:
        crumb_html = nav.group(1)
        for a_match in re.finditer(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', crumb_html, flags=re.I):
            href, text = a_match.group(1), a_match.group(2).strip()
            if href == "/" or href.startswith("https://emailtooladviser.com/"):
                items.append((text, href if href.startswith("http") else f"https://emailtooladviser.com{href}"))
            elif href.startswith("/"):
                items.append((text, f"https://emailtooladviser.com{href}"))
        # last item (no href) - get from the H1
        last_text_match = re.search(r'</a>\s*<span>›</span>\s*([A-Za-z][^<]+)', crumb_html)
        if last_text_match:
            items.append((last_text_match.group(1).strip(), fallback_url))
    return items


# ----------------------------------------------------------------------
# Rebuild
# ----------------------------------------------------------------------

def render_blocks(blocks: list[dict]) -> str:
    return "\n".join(
        '<script type="application/ld+json">\n' + json.dumps(b, ensure_ascii=False) + "\n</script>"
        for b in blocks
    )


def rebuild_one(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    headline = extract_h1(html)
    desc = extract_meta(html)
    canonical = extract_canonical(html)
    if not (headline and desc and canonical):
        return False
    blocks: list[dict] = [article(headline, desc, canonical)]
    crumbs = extract_breadcrumb_items(html, canonical)
    if len(crumbs) >= 2:
        blocks.append(breadcrumb(crumbs))
    faqs = extract_faqs(html)
    if faqs:
        blocks.append(faq(faqs))
    rel = path.relative_to(SITE_ROOT).as_posix()
    if rel.startswith("reviews/") and rel.endswith("-review.html"):
        # Extract the rating from rating-card if present.
        m = re.search(r'<div class="score">\s*(\d\.\d)', html)
        if m:
            tool = headline.split("Review")[0].strip()
            blocks.append(review(tool, float(m.group(1))))

    # Replace existing schema blocks with the rebuild.
    new_schema_html = render_blocks(blocks)
    pattern = re.compile(r'\s*<script type="application/ld\+json">[\s\S]*?</script>', flags=re.I)
    cleaned = pattern.sub("", html, count=10)
    # Inject just before </head>
    if "</head>" not in cleaned:
        return False
    new_html = cleaned.replace("</head>", new_schema_html + "\n</head>", 1)
    if new_html == html:
        return False
    path.write_text(new_html, encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true",
                        help="Re-emit schema blocks across every HTML file.")
    args = parser.parse_args()

    if not args.rebuild:
        print("Use --rebuild to refresh schema blocks in every HTML file.")
        print("Or import the builder functions: article, review, faq, breadcrumb, howto.")
        return

    count = 0
    for p in SITE_ROOT.rglob("*.html"):
        if any(d in EXCLUDE_DIRS for d in p.relative_to(SITE_ROOT).parts):
            continue
        if rebuild_one(p):
            count += 1
            print(f"  ✓ {p.relative_to(SITE_ROOT)}")
    print(f"Rebuilt schema in {count} files.")


if __name__ == "__main__":
    main()
