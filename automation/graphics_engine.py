#!/usr/bin/env python3
"""SVG graphic engine for the EmailToolAdviser network.

Renders crisp, branded SVG graphics from article data:
  - cover.svg      — hero replacement (editorial cover treatment)
  - comparison.svg — two-column tool comparison
  - data.svg       — horizontal bar chart
  - score.svg      — editorial scorecard
  - pricing.svg    — tier cards

Per-site accent color comes from --color-brand.

Run via the runner script (deploy_graphics.py) which iterates sites
and articles, writes SVGs to <site>/assets/graphics/, and rewrites
HTML image refs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import textwrap

# ============================================================
# Tokens
# ============================================================
INK       = "#0f172a"
INK_SOFT  = "#334155"
MUTED     = "#64748b"
BORDER    = "#e2e8f0"
BG_SOFT   = "#f8fafc"
SUCCESS   = "#22c55e"
WARN      = "#f59e0b"
DANGER    = "#ef4444"
WHITE     = "#ffffff"


def darken(hex6: str, frac: float = 0.18) -> str:
    """Slightly darken a hex color."""
    h = hex6.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, int(r * (1 - frac)))
    g = max(0, int(g * (1 - frac)))
    b = max(0, int(b * (1 - frac)))
    return f"#{r:02x}{g:02x}{b:02x}"


def lighten(hex6: str, frac: float = 0.85) -> str:
    """Lighten a hex by blending toward white."""
    h = hex6.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r + (255 - r) * frac)
    g = int(g + (255 - g) * frac)
    b = int(b + (255 - b) * frac)
    return f"#{r:02x}{g:02x}{b:02x}"


FONT_STYLE = """
<style>
  .serif  { font-family: Georgia, 'Times New Roman', 'Playfair Display', serif; font-weight: 800; }
  .sans   { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .label  { font-family: system-ui, sans-serif; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
</style>
""".strip()


def esc(s: str) -> str:
    """Escape text for SVG embedding."""
    return html.escape(s or "", quote=False)


# ============================================================
# 1. COVER GRAPHIC — editorial hero replacement (1200×630)
# ============================================================
def cover_svg(
    *,
    accent: str,
    brand_name: str,
    eyebrow: str,
    title: str,
    subtitle: str,
    badge_text: str = "",
    stat_value: str = "",
    stat_label: str = "",
) -> str:
    """Editorial cover graphic. 1200x630 (OG image standard)."""
    accent_dark = darken(accent, 0.20)
    accent_soft = lighten(accent, 0.92)

    title_lines = textwrap.wrap(title, width=24)[:3]
    title_blocks = ""
    y = 240
    for i, line in enumerate(title_lines):
        title_blocks += (
            f'<text x="70" y="{y + i*72}" class="serif" font-size="64" fill="{INK}">{esc(line)}</text>'
        )

    badge_block = ""
    if badge_text:
        badge_block = (
            f'<g><rect x="70" y="140" rx="100" ry="100" width="{20 + 10*len(badge_text)}" '
            f'height="32" fill="{accent}"/>'
            f'<text x="{82}" y="161" class="label" font-size="12" fill="{WHITE}">{esc(badge_text)}</text></g>'
        )

    stat_block = ""
    if stat_value:
        stat_block = (
            f'<g transform="translate(820, 250)">'
            f'<rect x="0" y="0" rx="16" ry="16" width="320" height="240" fill="{WHITE}" '
            f'stroke="{BORDER}" stroke-width="1"/>'
            f'<text x="160" y="92" class="serif" font-size="84" fill="{accent}" text-anchor="middle">{esc(stat_value)}</text>'
            f'<text x="160" y="140" class="label" font-size="11" fill="{MUTED}" text-anchor="middle">{esc(stat_label)}</text>'
            f'<line x1="40" y1="170" x2="280" y2="170" stroke="{BORDER}"/>'
            f'<text x="160" y="200" class="sans" font-size="12" fill="{INK_SOFT}" text-anchor="middle" font-weight="600">EmailToolAdviser editorial</text>'
            f'</g>'
        )

    return f"""<svg viewBox="0 0 1200 630" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img">
{FONT_STYLE}
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{accent_soft}"/>
    <stop offset="100%" stop-color="{WHITE}"/>
  </linearGradient>
  <linearGradient id="strip" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="{accent}"/>
    <stop offset="100%" stop-color="{accent_dark}"/>
  </linearGradient>
</defs>
<rect width="1200" height="630" fill="url(#bg)"/>
<rect width="1200" height="6" fill="url(#strip)"/>
<text x="70" y="90" class="label" font-size="13" fill="{accent}">{esc(brand_name.upper())}</text>
<text x="70" y="115" class="sans" font-size="13" fill="{MUTED}">{esc(eyebrow)}</text>
{badge_block}
{title_blocks}
<text x="70" y="{240 + 72*len(title_lines) + 26}" class="sans" font-size="20" fill="{INK_SOFT}" font-weight="400">{esc(subtitle)}</text>
{stat_block}
<text x="70" y="600" class="sans" font-size="12" fill="{MUTED}" font-weight="500">Tested 90 days · 12 platforms · 350+ campaigns</text>
</svg>"""


# ============================================================
# 2. COMPARISON GRAPHIC (two-column comparison) — 800×540
# ============================================================
@dataclass
class ComparisonRow:
    label: str
    a_val: str
    b_val: str
    a_winner: bool = False


def comparison_svg(
    *,
    accent: str,
    title: str,
    tool_a_name: str,
    tool_b_name: str,
    rows: list[ComparisonRow],
    winner: str = "a",            # "a" or "b"
    footnote: str = "EmailToolAdviser testing, 2026",
) -> str:
    accent_dark = darken(accent, 0.18)
    accent_soft = lighten(accent, 0.92)

    row_h   = 56
    head_h  = 76
    body_y  = 110
    table_w = 720
    col_lbl_w = 220
    col_w   = (table_w - col_lbl_w) // 2
    x_lbl   = 40
    x_a     = 40 + col_lbl_w
    x_b     = 40 + col_lbl_w + col_w

    rows_svg = ""
    for i, r in enumerate(rows):
        y = body_y + head_h + i * row_h
        zebra = BG_SOFT if i % 2 == 1 else WHITE
        rows_svg += (
            f'<rect x="{x_lbl}" y="{y}" width="{table_w}" height="{row_h}" fill="{zebra}"/>'
            f'<text x="{x_lbl+18}" y="{y+34}" class="label" font-size="11" fill="{MUTED}">{esc(r.label)}</text>'
            f'<text x="{x_a+col_w//2}" y="{y+34}" class="sans" font-size="15" fill="{INK}" '
            f'text-anchor="middle" font-weight="{800 if r.a_winner else 500}">{esc(r.a_val)}</text>'
            f'<text x="{x_b+col_w//2}" y="{y+34}" class="sans" font-size="15" fill="{INK}" '
            f'text-anchor="middle" font-weight="{800 if not r.a_winner else 500}">{esc(r.b_val)}</text>'
        )

    a_header_fill = accent if winner == "a" else INK
    b_header_fill = accent if winner == "b" else INK
    a_badge = f'<g><rect x="{x_a+8}" y="{body_y+12}" rx="50" ry="50" width="74" height="20" fill="{WHITE}"/><text x="{x_a+45}" y="{body_y+26}" class="label" font-size="10" fill="{a_header_fill}" text-anchor="middle">WINNER</text></g>' if winner == "a" else ""
    b_badge = f'<g><rect x="{x_b+8}" y="{body_y+12}" rx="50" ry="50" width="74" height="20" fill="{WHITE}"/><text x="{x_b+45}" y="{body_y+26}" class="label" font-size="10" fill="{b_header_fill}" text-anchor="middle">WINNER</text></g>' if winner == "b" else ""

    total_h = body_y + head_h + len(rows) * row_h + 70

    return f"""<svg viewBox="0 0 800 {total_h}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img">
{FONT_STYLE}
<rect width="800" height="{total_h}" fill="{WHITE}"/>
<rect x="20" y="20" rx="14" ry="14" width="760" height="{total_h-40}" fill="{WHITE}" stroke="{BORDER}" stroke-width="1"/>
<text x="40" y="65" class="serif" font-size="26" fill="{INK}">{esc(title)}</text>
<text x="40" y="90" class="sans" font-size="13" fill="{MUTED}">Apples-to-apples editorial scoring</text>

<!-- table headers -->
<rect x="{x_lbl}" y="{body_y}" width="{col_lbl_w}" height="{head_h}" fill="{BG_SOFT}"/>
<rect x="{x_a}" y="{body_y}" width="{col_w}" height="{head_h}" fill="{a_header_fill}"/>
<rect x="{x_b}" y="{body_y}" width="{col_w}" height="{head_h}" fill="{b_header_fill}"/>
<text x="{x_lbl+18}" y="{body_y+45}" class="label" font-size="11" fill="{MUTED}">CRITERIA</text>
<text x="{x_a+col_w//2}" y="{body_y+50}" class="serif" font-size="20" fill="{WHITE}" text-anchor="middle">{esc(tool_a_name)}</text>
<text x="{x_b+col_w//2}" y="{body_y+50}" class="serif" font-size="20" fill="{WHITE}" text-anchor="middle">{esc(tool_b_name)}</text>
{a_badge}{b_badge}

{rows_svg}

<text x="40" y="{total_h-28}" class="sans" font-size="11" fill="{MUTED}">Source: {esc(footnote)}</text>
</svg>"""


# ============================================================
# 3. DATA / BAR CHART — 800×500
# ============================================================
@dataclass
class BarRow:
    label: str
    value: float
    display: str = ""   # e.g. "97.4%" — falls back to value
    highlight: bool = False


def data_svg(
    *,
    accent: str,
    title: str,
    subtitle: str,
    rows: list[BarRow],
    footnote: str = "EmailToolAdviser testing, 2026",
    value_axis_label: str = "",
) -> str:
    accent_soft = lighten(accent, 0.88)
    bar_h   = 36
    bar_gap = 16
    label_w = 200
    bar_x   = 220
    bar_w_max = 460
    top     = 110
    rows_h  = len(rows) * (bar_h + bar_gap)
    total_h = top + rows_h + 70

    vmax = max(r.value for r in rows) if rows else 1
    rows_svg = ""
    for i, r in enumerate(rows):
        y = top + i * (bar_h + bar_gap)
        w = max(8, int(bar_w_max * (r.value / vmax)))
        fill = accent if r.highlight else accent_soft
        text_fill = WHITE if r.highlight else INK
        rows_svg += (
            f'<text x="{label_w}" y="{y+24}" class="sans" font-size="14" fill="{INK_SOFT}" text-anchor="end" font-weight="600">{esc(r.label)}</text>'
            f'<rect x="{bar_x}" y="{y}" rx="6" ry="6" width="{w}" height="{bar_h}" fill="{fill}"/>'
            f'<text x="{bar_x + w - 12}" y="{y+24}" class="sans" font-size="13" fill="{text_fill}" text-anchor="end" font-weight="700">{esc(r.display or str(r.value))}</text>'
        )

    return f"""<svg viewBox="0 0 800 {total_h}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img">
{FONT_STYLE}
<rect width="800" height="{total_h}" fill="{WHITE}"/>
<rect x="20" y="20" rx="14" ry="14" width="760" height="{total_h-40}" fill="{WHITE}" stroke="{BORDER}" stroke-width="1"/>
<text x="40" y="60" class="serif" font-size="26" fill="{INK}">{esc(title)}</text>
<text x="40" y="85" class="sans" font-size="13" fill="{MUTED}">{esc(subtitle)}</text>
{rows_svg}
<text x="40" y="{total_h-28}" class="sans" font-size="11" fill="{MUTED}">Source: {esc(footnote)}</text>
</svg>"""


# ============================================================
# 4. SCORE VISUAL (editorial scorecard) — 720×640
# ============================================================
@dataclass
class SubScore:
    label: str
    score: float          # 0-5
    weight: int = 10      # percent


def score_svg(
    *,
    accent: str,
    tool_name: str,
    overall_score: float,
    sub_scores: list[SubScore],
    verdict: str = "",
    footnote: str = "EmailToolAdviser editorial scoring",
) -> str:
    accent_soft = lighten(accent, 0.88)
    bar_h   = 16
    row_h   = 44
    top     = 290
    cnt     = len(sub_scores)
    total_h = top + cnt * row_h + 80

    # Header score block
    header = (
        f'<rect x="20" y="20" rx="14" ry="14" width="680" height="{total_h-40}" fill="{WHITE}" stroke="{BORDER}" stroke-width="1"/>'
        f'<text x="40" y="60" class="label" font-size="11" fill="{accent}">EDITORIAL SCORECARD</text>'
        f'<text x="40" y="100" class="serif" font-size="32" fill="{INK}">{esc(tool_name)}</text>'
        f'<g transform="translate(40, 130)">'
        f'<text x="0" y="80" class="serif" font-size="96" fill="{accent}">{overall_score:.1f}</text>'
        f'<text x="135" y="80" class="serif" font-size="32" fill="{MUTED}">/ 5</text>'
        f'</g>'
    )

    # Verdict pill
    if verdict:
        header += (
            f'<g transform="translate(400, 150)">'
            f'<rect x="0" y="0" rx="100" ry="100" width="280" height="36" fill="{accent_soft}"/>'
            f'<text x="140" y="24" class="label" font-size="12" fill="{accent}" text-anchor="middle">{esc(verdict.upper())}</text>'
            f'</g>'
        )

    bars = ""
    for i, s in enumerate(sub_scores):
        y = top + i * row_h
        bar_w = int(560 * (s.score / 5))
        bars += (
            f'<text x="40" y="{y+12}" class="sans" font-size="13" fill="{INK_SOFT}" font-weight="600">{esc(s.label)}</text>'
            f'<text x="660" y="{y+12}" class="sans" font-size="13" fill="{INK}" text-anchor="end" font-weight="700">{s.score:.1f}</text>'
            f'<rect x="40" y="{y+18}" rx="4" ry="4" width="560" height="{bar_h}" fill="{BG_SOFT}"/>'
            f'<rect x="40" y="{y+18}" rx="4" ry="4" width="{bar_w}" height="{bar_h}" fill="{accent}"/>'
        )

    return f"""<svg viewBox="0 0 720 {total_h}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img">
{FONT_STYLE}
<rect width="720" height="{total_h}" fill="{WHITE}"/>
{header}
<line x1="40" y1="260" x2="680" y2="260" stroke="{BORDER}"/>
{bars}
<text x="40" y="{total_h-28}" class="sans" font-size="11" fill="{MUTED}">{esc(footnote)}</text>
</svg>"""


# ============================================================
# 5. PRICING BREAKDOWN — tier cards 800×420
# ============================================================
@dataclass
class PricingTier:
    name: str
    price: str          # e.g. "$12/mo"
    sub: str = ""       # e.g. "Up to 500 contacts"
    features: list[str] = field(default_factory=list)
    recommended: bool = False


def pricing_svg(
    *,
    accent: str,
    tool_name: str,
    tiers: list[PricingTier],
    footnote: str = "Prices as of 2026, billed monthly",
) -> str:
    n = len(tiers)
    gap = 16
    pad = 40
    card_w = (800 - pad*2 - gap*(n-1)) // n
    top = 130
    card_h = 280
    total_h = top + card_h + 80

    cards = ""
    for i, t in enumerate(tiers):
        x = pad + i * (card_w + gap)
        is_rec = t.recommended
        border_color = accent if is_rec else BORDER
        stroke_w = 2 if is_rec else 1
        rec_badge = ""
        y_off = 0
        if is_rec:
            rec_badge = (
                f'<rect x="{x}" y="{top}" rx="12" ry="12" width="{card_w}" height="32" fill="{accent}"/>'
                f'<text x="{x + card_w//2}" y="{top+21}" class="label" font-size="11" fill="{WHITE}" text-anchor="middle">RECOMMENDED</text>'
            )
            y_off = 32

        feats = ""
        for j, f in enumerate(t.features[:5]):
            feats += (
                f'<g transform="translate({x+18}, {top + 165 + y_off + j*22})">'
                f'<circle cx="6" cy="6" r="6" fill="{accent}"/>'
                f'<path d="M3 6.5 l2 2 l4 -4" stroke="{WHITE}" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<text x="20" y="11" class="sans" font-size="12" fill="{INK_SOFT}">{esc(f)}</text>'
                f'</g>'
            )

        cards += (
            f'<rect x="{x}" y="{top}" rx="12" ry="12" width="{card_w}" height="{card_h}" fill="{WHITE}" stroke="{border_color}" stroke-width="{stroke_w}"/>'
            + rec_badge +
            f'<text x="{x+18}" y="{top + 60 + y_off}" class="label" font-size="11" fill="{MUTED}">{esc(t.name.upper())}</text>'
            f'<text x="{x+18}" y="{top + 110 + y_off}" class="serif" font-size="36" fill="{INK}">{esc(t.price)}</text>'
            f'<text x="{x+18}" y="{top + 138 + y_off}" class="sans" font-size="12" fill="{MUTED}">{esc(t.sub)}</text>'
            + feats
        )

    return f"""<svg viewBox="0 0 800 {total_h}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img">
{FONT_STYLE}
<rect width="800" height="{total_h}" fill="{WHITE}"/>
<rect x="20" y="20" rx="14" ry="14" width="760" height="{total_h-40}" fill="{WHITE}" stroke="{BORDER}" stroke-width="1"/>
<text x="40" y="65" class="serif" font-size="26" fill="{INK}">{esc(tool_name)} pricing</text>
<text x="40" y="90" class="sans" font-size="13" fill="{MUTED}">All plans, real prices, no surprises</text>
{cards}
<text x="40" y="{total_h-28}" class="sans" font-size="11" fill="{MUTED}">{esc(footnote)}</text>
</svg>"""
