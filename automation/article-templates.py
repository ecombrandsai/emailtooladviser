#!/usr/bin/env python3
"""
article-templates.py
====================

Library of HTML scaffolds for each article type. The content-generator
imports these to seed Claude with the right shell — Claude then fills in
the body text, picks the right comparison rows, and writes the FAQ Q&A.

Each template is a Python f-string-style block returned by a function.
None of them embed actual content text — they only emit structure,
metadata, schema, and the visible CTA/CSS skeleton.

Exposed functions:
    base_head(...)        →  <head> block with meta + schema
    site_header()         →  branded header
    breadcrumbs(...)      →  <nav class="breadcrumbs">
    cta_box(...)          →  one <div class="cta-box">
    canonical_comparison_table()  →  the 5-tool table
    pros_cons(...)        →  pros/cons block
    rating_card(...)      →  star + breakdown card
    faq_section(...)      →  exactly 5 <details class="faq-item">
    verdict_aside(...)    →  closing .verdict block
    site_footer()         →  full footer

Plus high-level scaffolds:
    how_to_article(meta, sections)
    comparison_article(meta)
    review_article(meta)
    best_of_article(meta)
    industry_article(meta)
"""

from __future__ import annotations

import html
import json
from datetime import datetime


# ----------------------------------------------------------------------
# Primitives
# ----------------------------------------------------------------------

def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def base_head(title: str, description: str, canonical: str,
              schema_blocks: list[dict] | None = None) -> str:
    schema_blocks = schema_blocks or []
    schema_html = "\n  ".join(
        '<script type="application/ld+json">\n  ' + json.dumps(b, ensure_ascii=False) + "\n  </script>"
        for b in schema_blocks
    )
    return f"""<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#2563eb">
  <title>{_esc(title)}</title>
  <meta name="description" content="{_esc(description)}">
  <link rel="canonical" href="{_esc(canonical)}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{_esc(title)}">
  <meta property="og:description" content="{_esc(description)}">
  <meta property="og:url" content="{_esc(canonical)}">
  <meta property="og:site_name" content="EmailToolAdviser">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{_esc(title)}">
  <meta name="twitter:description" content="{_esc(description)}">
  <link rel="stylesheet" href="/css/styles.css">
  {schema_html}
</head>"""


def site_header(brand_name: str = "EmailToolAdviser") -> str:
    return f"""<header class="site-header">
    <div class="container">
      <a href="/" class="logo">{_esc(brand_name)}</a>
      <nav class="main-nav" aria-label="Primary">
        <a href="/articles/">Articles</a>
        <a href="/comparisons/">Comparisons</a>
        <a href="/reviews/">Reviews</a>
        <a href="/about.html">About</a>
      </nav>
      <a href="https://join.constantcontact.com/join-now" class="btn" rel="sponsored noopener" target="_blank">Get Started with Constant Contact</a>
    </div>
  </header>"""


def breadcrumbs(items: list[tuple[str, str | None]]) -> str:
    parts = []
    for i, (label, href) in enumerate(items):
        if href:
            parts.append(f'<a href="{_esc(href)}">{_esc(label)}</a>')
        else:
            parts.append(_esc(label))
        if i < len(items) - 1:
            parts.append('<span>›</span>')
    inner = " ".join(parts)
    return f"""<nav class="breadcrumbs" aria-label="Breadcrumb">
    <div class="container">
      {inner}
    </div>
  </nav>"""


CTA_PRICE_JUSTIFY = (
    "At just $12 per month, if your first email campaign brings back even one customer who spends more than $12, "
    "you have already made your money back. Most small businesses see returns of $36 for every $1 spent on email marketing."
)


def cta_box(headline: str, include_price_justify: bool = False,
            button_text: str = "Get Started with Constant Contact - Plans from $12/month") -> str:
    pj = f'\n    <p class="price-justify">{_esc(CTA_PRICE_JUSTIFY)}</p>' if include_price_justify else ""
    return f"""<div class="cta-box">
    <h3>{_esc(headline)}</h3>{pj}
    <a href="https://join.constantcontact.com/join-now" class="btn btn-lg" rel="sponsored noopener" target="_blank">{_esc(button_text)}</a>
  </div>"""


def canonical_comparison_table() -> str:
    return """<table class="comparison-table">
    <thead>
      <tr><th>Rank</th><th>Tool</th><th>Best For</th><th>Starting Price</th><th>Free Plan</th><th>Our Score</th></tr>
    </thead>
    <tbody>
      <tr class="winner"><td class="rank-1">1</td><td><strong>Constant Contact</strong></td><td>Small &amp; local businesses</td><td>$12/mo</td><td>60-day trial</td><td>4.8 / 5</td></tr>
      <tr><td>2</td><td>MailerLite</td><td>Bloggers, side hustles</td><td>$10/mo</td><td>Yes (1k contacts)</td><td>4.0 / 5</td></tr>
      <tr><td>3</td><td>Mailchimp</td><td>Visual designers</td><td>$13/mo</td><td>Yes (500 contacts)</td><td>3.8 / 5</td></tr>
      <tr><td>4</td><td>ActiveCampaign</td><td>Advanced automation</td><td>$29/mo</td><td>14-day trial</td><td>3.7 / 5</td></tr>
      <tr><td>5</td><td>Brevo (Sendinblue)</td><td>Transactional + marketing</td><td>$9/mo</td><td>Yes (300/day)</td><td>3.5 / 5</td></tr>
    </tbody>
  </table>"""


def pros_cons(pros: list[str], cons: list[str]) -> str:
    pros_li = "".join(f"<li>{_esc(p)}</li>" for p in pros)
    cons_li = "".join(f"<li>{_esc(c)}</li>" for c in cons)
    return f"""<div class="pros-cons">
    <div class="pros"><h4>Pros</h4><ul>{pros_li}</ul></div>
    <div class="cons"><h4>Cons</h4><ul>{cons_li}</ul></div>
  </div>"""


def rating_card(score: float, breakdown: list[tuple[str, float]]) -> str:
    rows = "".join(
        f'<div><span>{_esc(k)}</span><span><strong>{v:.1f} / 5</strong></span></div>'
        for k, v in breakdown
    )
    return f"""<div class="rating-card">
    <div class="score">{score:.1f}<small>/5</small></div>
    <div class="breakdown">{rows}</div>
  </div>"""


def faq_section(qs_and_as: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<details class="faq-item"><summary>{_esc(q)}</summary><div class="answer"><p>{_esc(a)}</p></div></details>'
        for q, a in qs_and_as
    )
    return f"""<section class="faq">
    <h2>Frequently Asked Questions</h2>
    {items}
  </section>"""


def verdict_aside(headline: str, body: str) -> str:
    return f"""<aside class="verdict">
    <h2>{_esc(headline)}</h2>
    <p>{_esc(body)}</p>
    <a href="https://join.constantcontact.com/join-now" class="btn btn-lg" rel="sponsored noopener" target="_blank">Get Started with Constant Contact - Plans from $12/month</a>
  </aside>"""


def site_footer() -> str:
    return """<footer class="site-footer">
    <div class="container">
      <div class="footer-grid">
        <div>
          <h4>EmailToolAdviser</h4>
          <p class="brand-blurb">The independent adviser for small businesses comparing email marketing tools. Reviews are written by our editorial team and updated monthly.</p>
        </div>
        <div>
          <h4>Sections</h4>
          <ul>
            <li><a href="/articles/">Articles</a></li>
            <li><a href="/comparisons/">Comparisons</a></li>
            <li><a href="/reviews/">Reviews</a></li>
          </ul>
        </div>
        <div>
          <h4>Top picks</h4>
          <ul>
            <li><a href="/reviews/constant-contact-review.html">Constant Contact</a></li>
            <li><a href="/comparisons/constant-contact-vs-mailchimp.html">vs Mailchimp</a></li>
            <li><a href="/comparisons/constant-contact-vs-mailerlite.html">vs MailerLite</a></li>
          </ul>
        </div>
        <div>
          <h4>About</h4>
          <ul>
            <li><a href="/about.html">About us</a></li>
            <li><a href="/contact.html">Contact</a></li>
          </ul>
        </div>
      </div>
      <div class="legal">
        <p><strong>Affiliate disclosure:</strong> This site contains affiliate links. We may earn a commission when you purchase through our links at no extra cost to you. Our recommendations are independent and based on hands-on testing.</p>
        <p>&copy; 2026 EmailToolAdviser. All rights reserved.</p>
      </div>
    </div>
  </footer>"""


# ----------------------------------------------------------------------
# Schema builders
# ----------------------------------------------------------------------

def article_schema(headline: str, description: str, canonical: str,
                   date_published: str | None = None) -> dict:
    date_published = date_published or datetime.now().date().isoformat()
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "author": {"@type": "Organization", "name": "EmailToolAdviser Editorial Team",
                   "url": "https://emailtooladviser.com/about.html"},
        "publisher": {"@type": "Organization", "name": "EmailToolAdviser",
                       "logo": {"@type": "ImageObject", "url": "https://emailtooladviser.com/logo.png"}},
        "datePublished": date_published,
        "dateModified": date_published,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }


def breadcrumb_schema(items: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
            for i, (name, url) in enumerate(items)
        ],
    }


def faq_schema(qs_and_as: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qs_and_as
        ],
    }


def howto_schema(name: str, steps: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": name,
        "step": [
            {"@type": "HowToStep", "name": title, "text": desc, "position": i + 1}
            for i, (title, desc) in enumerate(steps)
        ],
    }


def review_schema(name: str, rating: float, best: float = 5) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Review",
        "itemReviewed": {"@type": "SoftwareApplication", "name": name,
                          "applicationCategory": "BusinessApplication",
                          "operatingSystem": "Web"},
        "author": {"@type": "Organization", "name": "EmailToolAdviser Editorial Team"},
        "reviewRating": {"@type": "Rating", "ratingValue": str(rating),
                          "bestRating": str(best)},
        "datePublished": datetime.now().date().isoformat(),
    }


# ----------------------------------------------------------------------
# High-level scaffolds — returned as partial HTML for Claude to flesh out.
# Each scaffold names the placeholders with {{TOKEN}} so the caller can
# substitute via str.replace before sending.
# ----------------------------------------------------------------------

def how_to_article_scaffold() -> str:
    return """<!DOCTYPE html>
<html lang="en">
{HEAD}
<body>
  {HEADER}
  {BREADCRUMBS}
  <main>
    <section class="article-header">
      <div class="container container-narrow">
        <div class="meta">
          <span>By EmailToolAdviser Editorial Team</span>
          <span>Updated {DATE}</span>
          <span>{READ_TIME} min read</span>
        </div>
        <h1>{H1}</h1>
        <p class="lede">{LEDE}</p>
        <div class="affiliate-disclosure">This page contains affiliate links. We may earn a commission at no extra cost to you.</div>
      </div>
    </section>
    <section class="article-body">
      <div class="container container-narrow">
        {BODY}
        {CTA_AFTER_INTRO}
        {COMPARISON_TABLE}
        {CTA_MAIN}
        {SECTIONS}
        {CTA_PRE_FAQ}
        {FAQ}
        {VERDICT}
      </div>
    </section>
  </main>
  {FOOTER}
  <script src="/js/main.js"></script>
</body>
</html>"""


def comparison_article_scaffold() -> str:
    return how_to_article_scaffold()  # Same shell; comparison-specific HTML in BODY/SECTIONS.


def review_article_scaffold() -> str:
    return """<!DOCTYPE html>
<html lang="en">
{HEAD}
<body>
  {HEADER}
  {BREADCRUMBS}
  <main>
    <section class="article-header">
      <div class="container container-narrow">
        <div class="meta">
          <span>By EmailToolAdviser Editorial Team</span>
          <span>Updated {DATE}</span>
          <span>{READ_TIME} min read</span>
        </div>
        <h1>{H1}</h1>
        <p class="lede">{LEDE}</p>
        <div class="affiliate-disclosure">This page contains affiliate links. We may earn a commission at no extra cost to you.</div>
      </div>
    </section>
    <section class="article-body">
      <div class="container container-narrow">
        <h2>{VERDICT_HEADLINE}</h2>
        {RATING_CARD}
        {CTA_AFTER_INTRO}
        {BODY}
        {PROS_CONS}
        {CTA_MAIN}
        {COMPARISON_TABLE}
        {FAQ}
        {VERDICT}
      </div>
    </section>
  </main>
  {FOOTER}
  <script src="/js/main.js"></script>
</body>
</html>"""


def best_of_article_scaffold() -> str:
    return how_to_article_scaffold()


def industry_article_scaffold() -> str:
    return how_to_article_scaffold()


# ----------------------------------------------------------------------
# Read-time helper
# ----------------------------------------------------------------------

def estimate_read_time(word_count: int, wpm: int = 230) -> int:
    import math
    return max(1, math.ceil(word_count / wpm))
