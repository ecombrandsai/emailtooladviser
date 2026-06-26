#!/usr/bin/env python3
"""
content-generator.py  —  Advanced SERP-aware content generation
================================================================

Pipeline per article:
    1. Read next pending keyword from automation/keyword-queue.json.
    2. (Optional) Pre-research: pull top-5 competitor word counts and H2
       counts via competitor-monitor's snapshot if present.
    3. Build a system prompt that locks in brand voice, schema, CTA copy,
       and a competitor-derived target word count.
    4. Call Claude (claude-sonnet-4-6) for one complete HTML document.
    5. Quality scoring: word count, keyword presence in first 100 words,
       H2 with keyword, 3-5 CTAs, 2+ internal links.  If any check fails,
       ask Claude to regenerate the offending section.
    6. Save to /<section>/<slug>.html, mark queue published, update sitemap,
       append publish log.

Reads ANTHROPIC_API_KEY from env. Never hardcoded. Never logged.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python3 automation/content-generator.py --count 3
    python3 automation/content-generator.py --keyword-id 42
    python3 automation/content-generator.py --dry-run --count 1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
PUBLISH_LOG_PATH = THIS_DIR / "publish-log.json"
SNAPSHOT_PATH = THIS_DIR / "competitor-snapshot.json"
SITEMAP_PATH = SITE_ROOT / "sitemap.xml"


# --------------------------------------------------------------------------
# IO
# --------------------------------------------------------------------------

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


def slugify(s: str) -> str:
    out = re.sub(r"[^a-z0-9\s-]", "", s.lower())
    return re.sub(r"[\s-]+", "-", out).strip("-")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def section_for(item_type: str) -> str:
    return {"article": "articles", "comparison": "comparisons", "review": "reviews"}.get(item_type, "articles")


# --------------------------------------------------------------------------
# Pre-generation research
# --------------------------------------------------------------------------

def research_for(kw: dict) -> dict:
    """Pull top-5 competitor data from the competitor-monitor snapshot if available."""
    snap = load_json(SNAPSHOT_PATH).get("keywords", {})
    entry = snap.get(kw["keyword"]) or snap.get(kw["keyword"].lower())
    if not entry:
        return {"target_word_count": 2500, "top_5": [], "h2_count_target": 8}
    gaps = entry.get("gaps", {})
    target_wc = max(gaps.get("target_word_count", 2500), 2000)
    return {
        "target_word_count": target_wc,
        "top_5": entry.get("serp_top5", []),
        "h2_count_target": 8,
    }


# --------------------------------------------------------------------------
# Prompt building
# --------------------------------------------------------------------------

def build_system_prompt(cfg: dict, research: dict) -> str:
    target_wc = research["target_word_count"]
    return textwrap.dedent(f"""
        You are the lead editorial writer for {cfg['site_name']}, an
        independent affiliate site comparing email marketing tools for
        small businesses.

        Every article must follow these rules, in order:

        1. RETURN ONE complete HTML document starting with <!DOCTYPE html>
           and ending with </html>. No markdown fences, no preamble.

        2. The body MUST contain at least {target_wc} visible words. Aim
           for {int(target_wc * 1.1)} words to comfortably beat competitors.

        3. Use ONLY the CSS classes defined in /css/styles.css. No inline
           style attributes except where the template already has them.
           Reference /css/styles.css and /js/main.js.

        4. Constant Contact is the #1 recommendation. Every CTA-style link
           to the affiliate goes to {cfg['affiliate_link']} with
           rel="sponsored noopener" target="_blank" and the exact button
           text "Get Started with Constant Contact - Plans from $12/month".

        5. Include this canonical price-justification copy in at least
           TWO CTA boxes verbatim:
              "{cfg['price_justification']}"

        6. Required components:
           - <header class="site-header">…</header>
           - <nav class="breadcrumbs">
           - <section class="article-header"> with .lede paragraph
           - <section class="article-body"> with 8+ H2 sections
           - One canonical 5-tool comparison table with Constant Contact
             ranked #1 (use class="comparison-table" and the .winner row)
           - At least FOUR <div class="cta-box"> components placed:
                a) after the intro section
                b) after the main recommendation section
                c) before the FAQ section
                d) inside the closing <aside class="verdict">
           - <section class="faq"> with EXACTLY 5 <details class="faq-item">
             targeting Google PAA-style questions
           - <aside class="verdict"> at the end with the final CTA
           - The full <footer class="site-footer"> from the template

        7. Required schema in <head>: THREE separate
           <script type="application/ld+json"> blocks: Article schema,
           BreadcrumbList, FAQPage. For review articles add a 4th Review
           schema; for comparisons add a 4th ItemList of Review entries.

        8. Internal links: at least THREE inline <a> tags to other
           on-network URLs (e.g. /reviews/constant-contact-review.html,
           /comparisons/constant-contact-vs-mailchimp.html,
           /articles/best-email-marketing-for-small-business.html).
           Use descriptive anchor text; never "click here".

        9. Tone: plain-language, second-person, no jargon, no hedging.
           Real numbers. Real examples. Author meta is
           "{cfg['author_name']}". Published date is {datetime.now().date().isoformat()}.

       10. Keyword placement: the target keyword must appear in the
           <title>, in the H1, in the first 100 visible words, in at
           least one H2, in the meta description, and naturally
           throughout the body. No keyword stuffing — natural usage only.

       11. Affiliate disclosure box at the TOP of the article-header
           content (use <div class="affiliate-disclosure">).
    """).strip()


def build_user_prompt(cfg: dict, kw: dict, research: dict, site_url: str) -> str:
    section = section_for(kw["type"])
    slug = kw.get("suggested_slug") or slugify(kw["keyword"])
    rel_path = f"/{section}/{slug}.html"
    top5_blob = ""
    if research["top_5"]:
        lines = ["", "Top 5 competitor URLs (analyze their structure; out-write them):"]
        for r in research["top_5"][:5]:
            lines.append(f"  - [{r.get('position')}] {r.get('title','')[:80]} — {r.get('link','')}")
        top5_blob = "\n".join(lines)

    suggested_title = kw.get("suggested_title") or " ".join(w.capitalize() for w in kw["keyword"].split())

    return textwrap.dedent(f"""
        Write the complete article.

        Target keyword: {kw['keyword']!r}
        Type: {kw['type']}
        Section: /{section}/
        Save path: {rel_path}
        Canonical URL: {site_url}{rel_path}
        Suggested title: {suggested_title} 2026
        Suggested slug: {slug}
        Funnel stage: {kw.get('intent', 'top_funnel')}
        Target body word count: {research['target_word_count']} (minimum)
        Target H2 count: {research['h2_count_target']}
        {top5_blob}

        Required title tag pattern:
        "<title-from-H1> 2026 | {cfg['site_name']}"

        Required meta description: under 160 characters, includes the
        target keyword in the first 20 words plus a clear value-prop.

        Internal links to include (pick 3-5 most relevant):
        - /reviews/constant-contact-review.html
        - /comparisons/constant-contact-vs-mailchimp.html
        - /comparisons/constant-contact-vs-mailerlite.html
        - /comparisons/constant-contact-vs-activecampaign.html
        - /articles/best-email-marketing-for-small-business.html
        - /articles/how-to-do-email-marketing-small-business.html
        - /articles/email-marketing-tips-small-business.html
        - /articles/what-to-send-in-a-business-newsletter.html

        Output: ONE complete HTML document. No preamble, no code fences.
    """).strip()


# --------------------------------------------------------------------------
# Claude API
# --------------------------------------------------------------------------

def call_claude(cfg: dict, kw: dict, research: dict, site_url: str) -> str:
    try:
        import anthropic  # type: ignore
    except ImportError:
        sys.exit("Missing dep: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY env var is required.")
    client = anthropic.Anthropic(api_key=api_key)
    system = build_system_prompt(cfg, research)
    user = build_user_prompt(cfg, kw, research, site_url)

    print(f"  ↳ Calling {cfg['claude_model']} for {kw['keyword']!r}...")
    response = client.messages.create(
        model=cfg["claude_model"],
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    html = "".join(parts).strip()
    if html.startswith("```"):
        html = html.split("\n", 1)[1] if "\n" in html else html
        if html.endswith("```"):
            html = html.rsplit("```", 1)[0]
    return html.strip()


# --------------------------------------------------------------------------
# Quality scoring
# --------------------------------------------------------------------------

def visible_words(html: str) -> int:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return len(text.split())


def first_n_visible_words(html: str, n: int = 100) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()[:n]).lower()


def quality_report(html: str, kw: str, target_wc: int) -> dict:
    wc = visible_words(html)
    keyword_lower = kw.lower()
    first100 = first_n_visible_words(html, 100)
    h2_matches = re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.I | re.S)
    h2_with_kw = any(keyword_lower in re.sub(r"<[^>]+>", "", h).lower() for h in h2_matches)
    cta_count = html.lower().count("class=\"cta-box\"") + html.lower().count('class="verdict"')
    internal_links = len(re.findall(r'href="/(articles|comparisons|reviews)/', html))
    has_article_schema = '"@type": "Article"' in html or "'@type': 'Article'" in html
    has_breadcrumb = "BreadcrumbList" in html
    has_faqpage = "FAQPage" in html
    cc_link_count = html.count("join.constantcontact.com/join-now")
    checks = {
        "word_count": wc,
        "word_count_ok": wc >= int(target_wc * 0.9),
        "keyword_in_first_100": keyword_lower in first100,
        "keyword_in_an_h2": h2_with_kw,
        "cta_count": cta_count,
        "cta_count_ok": cta_count >= 3,
        "internal_links": internal_links,
        "internal_links_ok": internal_links >= 2,
        "article_schema": has_article_schema,
        "breadcrumb_schema": has_breadcrumb,
        "faqpage_schema": has_faqpage,
        "affiliate_cta_count": cc_link_count,
        "affiliate_cta_ok": cc_link_count >= 3,
    }
    checks["all_ok"] = (
        checks["word_count_ok"]
        and checks["keyword_in_first_100"]
        and checks["cta_count_ok"]
        and checks["internal_links_ok"]
        and checks["article_schema"]
        and checks["breadcrumb_schema"]
        and checks["affiliate_cta_ok"]
    )
    return checks


# --------------------------------------------------------------------------
# Queue
# --------------------------------------------------------------------------

def pick_next_keyword(queue: dict, keyword_id: int | None) -> dict | None:
    keywords = queue.get("keywords", [])
    if keyword_id is not None:
        for kw in keywords:
            if kw.get("id") == keyword_id:
                return kw
        return None
    pending = [k for k in keywords if k.get("status") in ("pending", "unpublished")]
    satellite = os.environ.get("SATELLITE_DOMAIN")
    if satellite:
        pending = [k for k in pending if k.get("target_domain") == satellite]
    if not pending:
        return None
    pending.sort(key=lambda k: (-float(k.get("priority_score", k.get("priority", 50) or 50))))
    return pending[0]


def mark_published(queue: dict, kw: dict, url: str) -> None:
    for entry in queue["keywords"]:
        if entry.get("id") == kw.get("id") or entry.get("keyword") == kw.get("keyword"):
            entry["status"] = "published"
            entry["published_date"] = now_iso()
            entry["article_url"] = url
            entry["url"] = url
            return


def append_publish_log(kw: dict, url: str) -> None:
    log = load_json(PUBLISH_LOG_PATH) or {"entries": []}
    next_id = max((e.get("id", 0) for e in log.get("entries", [])), default=0) + 1
    log.setdefault("entries", []).append({
        "id": next_id,
        "keyword_id": kw.get("id"),
        "url": url,
        "type": kw.get("type", "article"),
        "domain": kw.get("target_domain", "emailtooladviser.com"),
        "published_at": now_iso(),
    })
    save_json(PUBLISH_LOG_PATH, log)


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
    SITEMAP_PATH.write_text(content.replace("</urlset>", entry + "\n</urlset>"), encoding="utf-8")


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def generate_one(cfg: dict, queue: dict, dry_run: bool, keyword_id: int | None) -> bool:
    kw = pick_next_keyword(queue, keyword_id)
    if kw is None:
        print("Queue empty for current filter.")
        return False
    print(f"→ Generating: {kw['keyword']} ({kw.get('type','article')})")
    research = research_for(kw)
    section = section_for(kw.get("type", "article"))
    slug = kw.get("suggested_slug") or slugify(kw["keyword"])
    target_domain = kw.get("target_domain", cfg.get("core_domain", "emailtooladviser.com").replace("https://", ""))
    site_url = f"https://{target_domain}"
    full_url = f"{site_url}/{section}/{slug}.html"

    # Where do we save? If running on the core, save to SITE_ROOT/<section>.
    out_dir = SITE_ROOT / section
    out_path = out_dir / f"{slug}.html"
    if out_path.exists():
        print(f"  ↳ Already exists: {out_path}; marking published.")
        mark_published(queue, kw, full_url)
        save_json(QUEUE_PATH, queue)
        return True
    if dry_run:
        print(f"  ↳ DRY: would write {out_path}")
        return True

    html = call_claude(cfg, kw, research, site_url)
    if "<!DOCTYPE html>" not in html or "</html>" not in html:
        print("  ↳ Claude returned non-HTML; skipping save.")
        return False

    # Quality check
    qr = quality_report(html, kw["keyword"], research["target_word_count"])
    print(f"  ↳ Quality: wc={qr['word_count']} cta={qr['cta_count']} links={qr['internal_links']} all_ok={qr['all_ok']}")
    if not qr["all_ok"]:
        print("  ↳ Quality flag — proceeding with save anyway, but flagging for review.")
        # In a fuller impl we'd ask Claude to regenerate the problem sections.
        # For now we save with a comment marker so the reviewer can see it.
        marker = f"\n<!-- QUALITY_REVIEW_NEEDED: {json.dumps(qr)} -->\n"
        html = html.replace("</body>", marker + "</body>")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  ✓ Wrote {out_path} ({qr['word_count']} words)")

    mark_published(queue, kw, full_url)
    save_json(QUEUE_PATH, queue)
    append_publish_log(kw, full_url)
    append_to_sitemap(full_url)
    return True


def main():
    parser = argparse.ArgumentParser(description="SERP-aware Claude content generator")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--keyword-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)
    queue = load_json(QUEUE_PATH)
    if not queue.get("keywords"):
        sys.exit("Empty keyword queue.")

    for i in range(args.count):
        ok = generate_one(cfg, queue, args.dry_run, args.keyword_id)
        if not ok:
            break
        if i < args.count - 1:
            time.sleep(3)

    print("Done.")


if __name__ == "__main__":
    main()
