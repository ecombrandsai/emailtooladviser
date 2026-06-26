#!/usr/bin/env python3
"""
content-generator.py
====================

Reads the next unpublished keyword from automation/keyword-queue.json,
asks Claude (claude-sonnet-4-6 by default) to write a complete HTML
article matching the site template, saves it to the correct folder,
updates the keyword queue, and appends to publish-log.json.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python3 content-generator.py --count 3
    python3 content-generator.py --keyword-id 42
    python3 content-generator.py --dry-run --count 1

Requires:
    pip install anthropic
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
PUBLISH_LOG_PATH = THIS_DIR / "publish-log.json"
SITEMAP_PATH = SITE_ROOT / "sitemap.xml"


# -----------------------------------------------------------------------------
# IO helpers
# -----------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def slugify(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def section_for(item_type: str) -> str:
    return {
        "article": "articles",
        "comparison": "comparisons",
        "review": "reviews",
    }.get(item_type, "articles")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -----------------------------------------------------------------------------
# Claude API
# -----------------------------------------------------------------------------

def build_system_prompt(cfg: dict) -> str:
    return textwrap.dedent(f"""
        You are an editorial writer for {cfg['site_name']}, an independent
        affiliate site for small businesses comparing email marketing tools.

        Every article you write follows these absolute rules:

        1. Return ONE complete HTML document starting with <!DOCTYPE html>
           and ending with </html>. No markdown, no preamble, no commentary.

        2. Use exactly the CSS classes from /css/styles.css. Never inline
           styles. Never link external stylesheets. Reference /css/styles.css
           and /js/main.js.

        3. Constant Contact is the #1 recommendation. Affiliate CTA URL is
           {cfg['affiliate_link']} with rel="sponsored noopener" target="_blank".

        4. Include the canonical price-justification copy in 2+ CTAs:
           "{cfg['price_justification']}"

        5. Required components: header.site-header, breadcrumbs, article-header
           with .lede, article-body with multiple H2 sections, comparison
           table with Constant Contact ranked #1, 4+ .cta-box components,
           5-question FAQ using <details class="faq-item">, .verdict closing
           aside, and the full site footer.

        6. Required schema in <head>: three or four <script type="application/ld+json">
           blocks — Article schema, BreadcrumbList, FAQPage, and Review/ItemList
           where appropriate.

        7. Tone: plain-language, second-person, no jargon, no hedging.
           Real specifics. Real numbers. Real examples.

        8. Affiliate disclosure box at the top of the article-header content.

        9. Author meta is "{cfg['author_name']}". Published date is today's
           ISO date. Read time = ceil(word_count / 230).
    """).strip()


def build_user_prompt(cfg: dict, kw: dict, site_url: str) -> str:
    section = section_for(kw["type"])
    slug = slugify(kw["keyword"])
    rel_path = f"/{section}/{slug}.html"

    return textwrap.dedent(f"""
        Write a complete HTML page targeting this keyword: {kw['keyword']!r}.

        Target word count: {cfg['content_min_words']}-{cfg['content_max_words']} body words.

        Type: {kw['type']}
        Section path: /{section}/
        Relative URL on this domain: {rel_path}
        Canonical URL: {site_url}{rel_path}

        Required H1 (or close variant): A descriptive title that includes the
        target keyword naturally.

        Required title tag pattern:
        "<H1-style title> 2026 | {cfg['site_name']}"

        Required meta description: under 160 characters, includes the
        target keyword naturally.

        Required H2 sections:
        - Lede / setup
        - Why this matters / context
        - The comparison or ranking (with the canonical 5-tool table)
        - Constant Contact-specific recommendation
        - Practical how-to / tips
        - FAQ (exactly 5 Q&As, 40-80 words each)
        - Verdict using .verdict component

        Internal links: at least 3 to other content on the site
        (/reviews/constant-contact-review.html,
         /comparisons/constant-contact-vs-mailchimp.html,
         /articles/best-email-marketing-for-small-business.html, etc.)

        Output: ONE complete HTML document, no preamble, no code fences.
    """).strip()


def call_claude(cfg: dict, kw: dict, site_url: str) -> str:
    try:
        import anthropic  # type: ignore
    except ImportError:
        sys.exit("Missing dependency. Run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set the ANTHROPIC_API_KEY environment variable before running.")

    client = anthropic.Anthropic(api_key=api_key)
    system = build_system_prompt(cfg)
    user = build_user_prompt(cfg, kw, site_url)

    print(f"  ↳ Asking {cfg['claude_model']} for {kw['keyword']!r}...")
    response = client.messages.create(
        model=cfg["claude_model"],
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    # Concatenate all text blocks.
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    html = "".join(parts).strip()

    # Strip markdown fences if the model added them despite instructions.
    if html.startswith("```"):
        html = html.split("\n", 1)[1] if "\n" in html else html
        if html.endswith("```"):
            html = html.rsplit("```", 1)[0]
    return html.strip()


# -----------------------------------------------------------------------------
# Queue management
# -----------------------------------------------------------------------------

def pick_next_keyword(queue: dict, keyword_id: int | None) -> dict | None:
    keywords = queue.get("keywords", [])
    if keyword_id is not None:
        for kw in keywords:
            if kw["id"] == keyword_id:
                return kw
        return None
    # Pick the next unpublished keyword by priority then id.
    unpublished = [k for k in keywords if k.get("status") == "unpublished"]
    if not unpublished:
        return None
    unpublished.sort(key=lambda k: (k.get("priority", 99), k["id"]))
    return unpublished[0]


def mark_published(queue: dict, kw: dict, url: str) -> None:
    for entry in queue["keywords"]:
        if entry["id"] == kw["id"]:
            entry["status"] = "published"
            entry["published_date"] = utc_now_iso()
            entry["url"] = url
            return


def append_publish_log(kw: dict, url: str) -> None:
    log = load_json(PUBLISH_LOG_PATH) if PUBLISH_LOG_PATH.exists() else {"entries": []}
    next_id = max((e.get("id", 0) for e in log.get("entries", [])), default=0) + 1
    log.setdefault("entries", []).append({
        "id": next_id,
        "keyword_id": kw["id"],
        "url": url,
        "type": kw["type"],
        "domain": kw["target_domain"],
        "published_at": utc_now_iso(),
    })
    save_json(PUBLISH_LOG_PATH, log)


# -----------------------------------------------------------------------------
# Sitemap (light update; full rebuild handled by sitemap-generator.py)
# -----------------------------------------------------------------------------

def append_to_sitemap(url: str) -> None:
    if not SITEMAP_PATH.exists():
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = textwrap.dedent(f"""
      <url>
        <loc>{url}</loc>
        <lastmod>{today}</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
      </url>
    """).strip()
    content = SITEMAP_PATH.read_text(encoding="utf-8")
    if url in content:
        return
    content = content.replace("</urlset>", entry + "\n</urlset>")
    SITEMAP_PATH.write_text(content, encoding="utf-8")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def generate_one(cfg: dict, queue: dict, dry_run: bool, keyword_id: int | None) -> bool:
    kw = pick_next_keyword(queue, keyword_id)
    if kw is None:
        print("No unpublished keywords remaining in the queue.")
        return False

    print(f"→ Generating: [{kw['id']}] {kw['keyword']} ({kw['type']})")
    section = section_for(kw["type"])
    slug = slugify(kw["keyword"])
    rel_path = f"/{section}/{slug}.html"
    site_url = f"https://{kw['target_domain']}"
    full_url = f"{site_url}{rel_path}"
    out_dir = SITE_ROOT / section
    out_path = out_dir / f"{slug}.html"

    if out_path.exists():
        print(f"  ↳ Already exists: {out_path}. Skipping.")
        mark_published(queue, kw, full_url)
        save_json(QUEUE_PATH, queue)
        return True

    if dry_run:
        print(f"  ↳ DRY RUN: would write {out_path}")
        return True

    html = call_claude(cfg, kw, site_url)
    if "<!DOCTYPE html>" not in html or "</html>" not in html:
        print("  ↳ Claude returned non-HTML output. Skipping save.")
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  ✓ Wrote {out_path}")

    mark_published(queue, kw, full_url)
    save_json(QUEUE_PATH, queue)
    append_publish_log(kw, full_url)
    append_to_sitemap(full_url)
    print(f"  ✓ Updated queue, publish-log, and sitemap.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate articles via Claude.")
    parser.add_argument("--count", type=int, default=1,
                        help="How many articles to generate this run.")
    parser.add_argument("--keyword-id", type=int, default=None,
                        help="Pick a specific keyword by ID.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't call Claude; show what would be written.")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)
    queue = load_json(QUEUE_PATH)

    for i in range(args.count):
        ok = generate_one(cfg, queue, args.dry_run, args.keyword_id)
        if not ok:
            break
        if i < args.count - 1:
            print("  ↳ Pausing 3s between generations.")
            time.sleep(3)

    print("Done.")


if __name__ == "__main__":
    main()
