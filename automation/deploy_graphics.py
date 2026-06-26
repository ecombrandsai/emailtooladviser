#!/usr/bin/env python3
"""Render branded SVG graphics for every article in the corpus, write to
each repo's assets/graphics/, and rewrite HTML image refs to use them."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, "/tmp")
from graphics_engine import (
    BarRow, ComparisonRow, PricingTier, SubScore,
    comparison_svg, cover_svg, data_svg, pricing_svg, score_svg,
)

NETWORK = Path("/Users/tmurph/Desktop/emailtooladviser-network")

SITE_BRAND = {
    "emailtooladviser":     ("#2563eb", "EmailToolAdviser"),
    "bestemailtoolreviews": ("#0ea5e9", "BestEmailToolReviews"),
    "emailmarketingrated":  ("#8b5cf6", "Email Marketing Rated"),
    "emailtoolratings":     ("#f59e0b", "Email Tool Ratings"),
    "smallbizemailhub":     ("#10b981", "SmallBiz Email Hub"),
}

# ---------- Canonical article data (curated from existing article content) ---

# Each article: slug → graphics manifest
ARTICLES = {
    # ARTICLES — listicles and how-tos
    "best-email-marketing-for-small-business": {
        "kind":     "listicle",
        "old_hero": "best-sb-hero.jpg",
        "title":    "Best Email Marketing for Small Business in 2026",
        "subtitle": "After testing 12 platforms for 90 days, one stood out for revenue.",
        "stat_value": "97.4%",
        "stat_label": "Inbox placement",
        "badge":    "EDITOR'S #1 PICK",
        "data": {
            "title":    "Deliverability — primary inbox placement",
            "subtitle": "Tested over 350 campaigns across 5 inbox providers",
            "rows": [
                BarRow(label="Constant Contact", value=97.4, display="97.4%", highlight=True),
                BarRow(label="MailerLite",       value=96.2, display="96.2%"),
                BarRow(label="Mailchimp",        value=94.8, display="94.8%"),
                BarRow(label="ActiveCampaign",   value=94.1, display="94.1%"),
                BarRow(label="Brevo",            value=92.7, display="92.7%"),
            ],
        },
        "pricing": {
            "tool":  "Constant Contact",
            "tiers": [
                PricingTier(name="Lite",     price="$12/mo", sub="Up to 500 contacts",
                            features=["Email campaigns","Templates","List builder","Basic reporting"]),
                PricingTier(name="Standard", price="$35/mo", sub="Up to 500 contacts",
                            features=["Automations","Segmentation","AI assistant","A/B testing","Phone support"], recommended=True),
                PricingTier(name="Premium",  price="$80/mo", sub="Up to 500 contacts",
                            features=["Revenue tracking","Dynamic content","Advanced reporting","Account manager"]),
            ],
        },
    },
    "best-email-marketing-for-local-businesses": {
        "kind":     "listicle",
        "old_hero": "local-hero.jpg",
        "title":    "Best Email Marketing for Local Businesses in 2026",
        "subtitle": "Phone-support-first, simple-billing-first — picked for the way local actually runs.",
        "stat_value": "$12",
        "stat_label": "Per month, all in",
        "badge":    "LOCAL BUSINESS PICK",
        "data": {
            "title":    "Best-for-local scoring",
            "subtitle": "How tools rate against local-business needs",
            "rows": [
                BarRow(label="Constant Contact", value=4.8, display="4.8 / 5", highlight=True),
                BarRow(label="MailerLite",       value=4.0, display="4.0 / 5"),
                BarRow(label="Mailchimp",        value=3.8, display="3.8 / 5"),
                BarRow(label="ActiveCampaign",   value=3.2, display="3.2 / 5"),
                BarRow(label="Brevo",            value=3.1, display="3.1 / 5"),
            ],
        },
    },
    "how-to-do-email-marketing-small-business": {
        "kind":     "how-to",
        "old_hero": "how-to-hero.jpg",
        "title":    "How to Do Email Marketing for a Small Business",
        "subtitle": "The 10-step plan we use for every small business client.",
        "stat_value": "$36",
        "stat_label": "Return per $1 spent",
        "badge":    "STEP-BY-STEP GUIDE",
        "data": {
            "title":    "Email ROI by tactic",
            "subtitle": "Average return per dollar spent",
            "rows": [
                BarRow(label="Abandoned cart",   value=44, display="$44", highlight=True),
                BarRow(label="Welcome series",   value=38, display="$38"),
                BarRow(label="Re-engagement",    value=29, display="$29"),
                BarRow(label="Weekly newsletter",value=22, display="$22"),
                BarRow(label="Cold acquisition", value=8,  display="$8"),
            ],
        },
    },
    "email-marketing-tips-small-business": {
        "kind":     "listicle",
        "old_hero": "tips-hero.jpg",
        "title":    "15 Email Marketing Tips Small Business Owners Wish They Knew Sooner",
        "subtitle": "Tactics that move the open rate, the click rate, and the revenue line.",
        "stat_value": "760%",
        "stat_label": "Open-rate lift from segmentation",
        "badge":    "EDITORIAL PLAYBOOK",
        "data": {
            "title":    "Open-rate impact by tactic",
            "subtitle": "Lift over baseline across small-business send tests",
            "rows": [
                BarRow(label="Segmented sends",   value=760, display="+760%", highlight=True),
                BarRow(label="Send-time A/B",     value=42,  display="+42%"),
                BarRow(label="Personalized subject", value=29, display="+29%"),
                BarRow(label="Plain-text format", value=17,  display="+17%"),
                BarRow(label="Emoji in subject",  value=8,   display="+8%"),
            ],
        },
    },
    "what-to-send-in-a-business-newsletter": {
        "kind":     "how-to",
        "old_hero": "newsletter-hero.jpg",
        "title":    "What to Send in a Small Business Newsletter",
        "subtitle": "The 6 newsletter blocks that earn the open and the click.",
        "stat_value": "6 blocks",
        "stat_label": "The editorial template",
        "badge":    "NEWSLETTER GUIDE",
        "data": {
            "title":    "Newsletter block click-through rates",
            "subtitle": "Median CTR by content block, small-business newsletters",
            "rows": [
                BarRow(label="Single-product spotlight",  value=4.8, display="4.8%", highlight=True),
                BarRow(label="Customer story",            value=3.9, display="3.9%"),
                BarRow(label="How-to / tutorial",         value=3.1, display="3.1%"),
                BarRow(label="Industry news",             value=1.8, display="1.8%"),
                BarRow(label="Generic announcement",      value=0.9, display="0.9%"),
            ],
        },
    },

    # COMPARISONS
    "constant-contact-vs-mailchimp": {
        "kind":     "comparison",
        "old_hero": "cc-vs-mc-hero.jpg",
        "title":    "Constant Contact vs Mailchimp: The Honest Comparison",
        "subtitle": "Phone support, deliverability, and price predictability — head to head.",
        "stat_value": "+2.6%",
        "stat_label": "CC deliverability edge",
        "badge":    "COMPARISON",
        "comparison": {
            "tool_a": "Constant Contact",
            "tool_b": "Mailchimp",
            "winner": "a",
            "rows": [
                ComparisonRow("Starting price",      "$12/mo",  "$13/mo",  a_winner=True),
                ComparisonRow("Phone support",       "Yes",     "No",      a_winner=True),
                ComparisonRow("Inbox placement",     "97.4%",   "94.8%",   a_winner=True),
                ComparisonRow("Templates",           "100+",    "200+",    a_winner=False),
                ComparisonRow("Automation depth",    "Solid",   "Best-in-class", a_winner=False),
                ComparisonRow("Best for",            "Small biz","Design-first brands", a_winner=True),
            ],
        },
        "pricing": {
            "tool":  "Constant Contact",
            "tiers": [
                PricingTier(name="Lite",     price="$12/mo", sub="500 contacts",
                            features=["Email","Templates","Reporting"]),
                PricingTier(name="Standard", price="$35/mo", sub="500 contacts",
                            features=["Automations","Segmentation","AI","A/B testing"], recommended=True),
                PricingTier(name="Premium",  price="$80/mo", sub="500 contacts",
                            features=["Revenue tracking","Dynamic content","Account mgr"]),
            ],
        },
    },
    "constant-contact-vs-mailerlite": {
        "kind":     "comparison",
        "old_hero": "cc-vs-ml-hero.jpg",
        "title":    "Constant Contact vs MailerLite: Which Wins for Small Business",
        "subtitle": "Polish vs. simplicity — and where the $12/mo entry tier earns its keep.",
        "stat_value": "$2",
        "stat_label": "Monthly delta — CC vs ML",
        "badge":    "COMPARISON",
        "comparison": {
            "tool_a": "Constant Contact",
            "tool_b": "MailerLite",
            "winner": "a",
            "rows": [
                ComparisonRow("Starting price",  "$12/mo",   "$10/mo",  a_winner=False),
                ComparisonRow("Free tier",       "60-day trial", "Yes (1k)", a_winner=False),
                ComparisonRow("Phone support",   "Yes",      "No",      a_winner=True),
                ComparisonRow("Templates",       "100+",     "75",      a_winner=True),
                ComparisonRow("Onboarding",      "Editorial","Self-serve", a_winner=True),
                ComparisonRow("Best for",        "Local biz","Solo creators", a_winner=True),
            ],
        },
    },
    "constant-contact-vs-activecampaign": {
        "kind":     "comparison",
        "old_hero": "cc-vs-ac-hero.jpg",
        "title":    "Constant Contact vs ActiveCampaign: SMB vs B2B",
        "subtitle": "When the automation depth justifies the price — and when it doesn't.",
        "stat_value": "$17",
        "stat_label": "Monthly delta",
        "badge":    "COMPARISON",
        "comparison": {
            "tool_a": "Constant Contact",
            "tool_b": "ActiveCampaign",
            "winner": "a",
            "rows": [
                ComparisonRow("Starting price",     "$12/mo",  "$29/mo",  a_winner=True),
                ComparisonRow("Phone support",      "Yes",     "No",      a_winner=True),
                ComparisonRow("Automation depth",   "Solid",   "Industry-leading", a_winner=False),
                ComparisonRow("Learning curve",    "Mild",    "Steep",   a_winner=True),
                ComparisonRow("CRM included",       "No",      "Yes",     a_winner=False),
                ComparisonRow("Best for",           "Small biz","B2B w/ sales team", a_winner=True),
            ],
        },
    },

    # REVIEWS
    "constant-contact-review": {
        "kind":     "review",
        "old_hero": "cc-review-hero.jpg",
        "title":    "Constant Contact Review 2026: 90-Day Test",
        "subtitle": "Phone support, $12 entry, 97.4% inbox placement — the small-business pick.",
        "stat_value": "4.8 / 5",
        "stat_label": "Editorial score",
        "badge":    "EDITOR'S #1 PICK",
        "score": {
            "tool":    "Constant Contact",
            "overall": 4.8,
            "verdict": "Top pick for small business",
            "subs": [
                SubScore("Ease of use",          5.0, 15),
                SubScore("Deliverability",       4.9, 20),
                SubScore("Support",              5.0, 15),
                SubScore("Templates",            4.5, 10),
                SubScore("Automation",           4.3, 10),
                SubScore("Price predictability", 4.9, 15),
                SubScore("Integrations",         4.5, 10),
            ],
        },
        "pricing": {
            "tool":  "Constant Contact",
            "tiers": [
                PricingTier(name="Lite",     price="$12/mo", sub="Up to 500 contacts",
                            features=["Email","Templates","Reporting"]),
                PricingTier(name="Standard", price="$35/mo", sub="Up to 500 contacts",
                            features=["Automations","Segmentation","AI","A/B","Phone support"], recommended=True),
                PricingTier(name="Premium",  price="$80/mo", sub="Up to 500 contacts",
                            features=["Revenue tracking","Dynamic content","Reports","Account mgr"]),
            ],
        },
    },
    "mailchimp-review": {
        "kind":     "review",
        "old_hero": None,
        "title":    "Mailchimp Review 2026",
        "subtitle": "Best-in-class templates, but a confusing pricing ladder.",
        "stat_value": "3.8 / 5",
        "stat_label": "Editorial score",
        "badge":    "REVIEW",
        "score": {
            "tool":    "Mailchimp",
            "overall": 3.8,
            "verdict": "Designer-friendly but pricey",
            "subs": [
                SubScore("Ease of use",          4.2, 15),
                SubScore("Deliverability",       4.4, 20),
                SubScore("Support",              3.4, 15),
                SubScore("Templates",            4.8, 10),
                SubScore("Automation",           4.0, 10),
                SubScore("Price predictability", 2.8, 15),
                SubScore("Integrations",         4.2, 10),
            ],
        },
    },
    "mailerlite-review": {
        "kind":     "review",
        "old_hero": None,
        "title":    "MailerLite Review 2026",
        "subtitle": "Cleanest builder in the category, with a real free tier — solo-creator pick.",
        "stat_value": "4.0 / 5",
        "stat_label": "Editorial score",
        "badge":    "REVIEW",
        "score": {
            "tool":    "MailerLite",
            "overall": 4.0,
            "verdict": "Best for solo creators",
            "subs": [
                SubScore("Ease of use",          4.7, 15),
                SubScore("Deliverability",       4.2, 20),
                SubScore("Support",              3.6, 15),
                SubScore("Templates",            4.0, 10),
                SubScore("Automation",           3.8, 10),
                SubScore("Price predictability", 4.5, 15),
                SubScore("Integrations",         3.7, 10),
            ],
        },
    },
}

# ---------- Article HTML file path lookup -----------------------------------

ARTICLE_PATHS = {
    "best-email-marketing-for-small-business":  "articles/best-email-marketing-for-small-business.html",
    "best-email-marketing-for-local-businesses":"articles/best-email-marketing-for-local-businesses.html",
    "how-to-do-email-marketing-small-business": "articles/how-to-do-email-marketing-small-business.html",
    "email-marketing-tips-small-business":      "articles/email-marketing-tips-small-business.html",
    "what-to-send-in-a-business-newsletter":    "articles/what-to-send-in-a-business-newsletter.html",
    "constant-contact-vs-mailchimp":            "comparisons/constant-contact-vs-mailchimp.html",
    "constant-contact-vs-mailerlite":           "comparisons/constant-contact-vs-mailerlite.html",
    "constant-contact-vs-activecampaign":       "comparisons/constant-contact-vs-activecampaign.html",
    "constant-contact-review":                  "reviews/constant-contact-review.html",
    "mailchimp-review":                         "reviews/mailchimp-review.html",
    "mailerlite-review":                        "reviews/mailerlite-review.html",
}


def render_all_for_article(slug: str, art: dict, accent: str, brand: str) -> dict[str, str]:
    """Returns dict of filename -> svg content for this article."""
    out: dict[str, str] = {}

    # Cover — always
    out[f"{slug}-cover.svg"] = cover_svg(
        accent=accent,
        brand_name=brand,
        eyebrow=art["kind"].replace("-", " ").upper(),
        title=art["title"],
        subtitle=art["subtitle"],
        badge_text=art.get("badge", ""),
        stat_value=art.get("stat_value", ""),
        stat_label=art.get("stat_label", ""),
    )

    # Decide which body graphics to generate
    if "data" in art:
        d = art["data"]
        out[f"{slug}-data.svg"] = data_svg(
            accent=accent,
            title=d["title"],
            subtitle=d["subtitle"],
            rows=d["rows"],
        )

    if "comparison" in art:
        c = art["comparison"]
        out[f"{slug}-comparison.svg"] = comparison_svg(
            accent=accent,
            title=art["title"],
            tool_a_name=c["tool_a"],
            tool_b_name=c["tool_b"],
            rows=c["rows"],
            winner=c["winner"],
        )

    if "score" in art:
        s = art["score"]
        out[f"{slug}-score.svg"] = score_svg(
            accent=accent,
            tool_name=s["tool"],
            overall_score=s["overall"],
            sub_scores=s["subs"],
            verdict=s.get("verdict",""),
        )

    if "pricing" in art:
        p = art["pricing"]
        out[f"{slug}-pricing.svg"] = pricing_svg(
            accent=accent,
            tool_name=p["tool"],
            tiers=p["tiers"],
        )

    return out


# ---------- HTML rewrites ----------------------------------------------------

def rewrite_hero_in_html(html_path: Path, slug: str, art: dict, accent: str) -> bool:
    """Replace the hero <img> with the new cover SVG. Returns True if changed."""
    text = html_path.read_text(encoding="utf-8")
    old_hero = art.get("old_hero")
    new_src = f"/assets/graphics/{slug}-cover.svg"
    alt = f"{art['title']} — editorial cover graphic"

    changed = False
    # 1. Replace any <img src="/images/<old_hero>" ...> with new cover SVG
    if old_hero:
        # Match img tags referencing /images/<old_hero> regardless of attribute order
        pattern = re.compile(
            r'<img\b[^>]*\bsrc="(?:/images/|images/)' + re.escape(old_hero) + r'"[^>]*/?>',
            re.IGNORECASE,
        )
        new_tag = (
            f'<img src="{new_src}" alt="{alt}" loading="eager" '
            f'style="width:100%;height:auto;border-radius:12px;display:block;" '
            f'class="hero hero-cover" />'
        )
        new_text, n = pattern.subn(new_tag, text)
        if n > 0:
            text = new_text
            changed = True

    # 2. Inject body graphics after the article-meta line if not already injected
    body_graphics = []
    if "data" in art:        body_graphics.append((f"{slug}-data.svg",        "data chart"))
    if "comparison" in art:  body_graphics.append((f"{slug}-comparison.svg",  "comparison graphic"))
    if "score" in art:       body_graphics.append((f"{slug}-score.svg",       "editorial scorecard"))
    if "pricing" in art:     body_graphics.append((f"{slug}-pricing.svg",     "pricing breakdown"))

    # Only inject if no existing reference to this slug's graphics
    if body_graphics and f"/assets/graphics/{slug}-" not in text.replace(new_src, ""):
        # Find insertion point: after the FIRST </h1> closing tag in the article body
        marker = "</h1>"
        idx = text.find(marker)
        if idx > 0:
            inject = ""
            for fname, kind in body_graphics:
                inject += (
                    f'\n<figure class="article-graphic" style="margin:32px 0;">'
                    f'<img src="/assets/graphics/{fname}" '
                    f'alt="{esc(art["title"])} — {kind}" '
                    f'loading="lazy" '
                    f'style="width:100%;height:auto;border-radius:12px;display:block;border:1px solid #e2e8f0;" />'
                    f'</figure>'
                )
            # Insert right after </h1>
            insert_pos = idx + len(marker)
            # Wrap inside a single block so it sits in the article body
            text = text[:insert_pos] + inject + text[insert_pos:]
            changed = True

    if changed:
        html_path.write_text(text, encoding="utf-8")
    return changed


def esc(s: str) -> str:
    import html
    return html.escape(s or "", quote=True)


# ---------- Runner -----------------------------------------------------------

def main():
    summary = {}
    for site, (accent, brand) in SITE_BRAND.items():
        graphics_dir = NETWORK / site / "assets" / "graphics"
        graphics_dir.mkdir(parents=True, exist_ok=True)

        n_svg = 0
        n_html = 0
        for slug, art in ARTICLES.items():
            svgs = render_all_for_article(slug, art, accent, brand)
            for fname, content in svgs.items():
                (graphics_dir / fname).write_text(content, encoding="utf-8")
                n_svg += 1

            # Update HTML if the article exists in this site
            rel = ARTICLE_PATHS.get(slug)
            if rel:
                p = NETWORK / site / rel
                if p.exists() and rewrite_hero_in_html(p, slug, art, accent):
                    n_html += 1

        summary[site] = (n_svg, n_html)
        print(f"  {site:30s} svg={n_svg:3d}  html_updated={n_html:3d}")

    print("\n=== Summary ===")
    for s, (svg, html_) in summary.items():
        print(f"  {s:30s} {svg} SVGs / {html_} articles back-filled")


if __name__ == "__main__":
    main()
