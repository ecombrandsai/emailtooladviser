#!/usr/bin/env python3
"""
weekly-report-generator.py
==========================

Runs every Monday at 08:00 UTC. Pulls last-week data from GSC, the
publish log, and our local snapshots; asks Claude to write an executive
summary; saves a dated HTML report to reports/weekly-YYYY-MM-DD.html
and a one-screen JSON summary to data/latest-report.json (dashboard
picks it up automatically).

Reads ANTHROPIC_API_KEY and GSC_SERVICE_ACCOUNT_JSON from env.

Usage:
    python3 automation/weekly-report-generator.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
PUBLISH_LOG = THIS_DIR / "publish-log.json"
CONFIG_PATH = THIS_DIR / "config.json"
RANKINGS = SITE_ROOT / "data" / "rankings.json"
REVENUE = SITE_ROOT / "data" / "revenue.json"
ALERTS = SITE_ROOT / "data" / "alerts.json"
LATEST_REPORT = SITE_ROOT / "data" / "latest-report.json"
REPORTS_DIR = SITE_ROOT / "reports"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(p: Path, d: dict | None = None) -> dict:
    if not p.exists():
        return d or {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------

def collect() -> dict:
    publish_log = load_json(PUBLISH_LOG, {"entries": []})
    rankings = load_json(RANKINGS)
    revenue = load_json(REVENUE)
    alerts = load_json(ALERTS)

    cutoff = date.today() - timedelta(days=7)
    last_week_articles = [
        e for e in publish_log.get("entries", [])
        if e.get("published_at", "")[:10] >= cutoff.isoformat()
    ]
    by_domain = defaultdict(int)
    for e in last_week_articles:
        by_domain[e.get("domain", "unknown")] += 1

    return {
        "window_start": cutoff.isoformat(),
        "window_end": date.today().isoformat(),
        "articles_published_count": len(last_week_articles),
        "articles_by_domain": dict(by_domain),
        "last_week_articles": last_week_articles,
        "rankings_summary": rankings.get("summary", {}),
        "movers_up": rankings.get("movers_up", [])[:10],
        "movers_down": rankings.get("movers_down", [])[:10],
        "new_entries": rankings.get("new_entries", [])[:10],
        "revenue": {
            "this_month": revenue.get("this_month_revenue", 0),
            "projected_next_month": revenue.get("projected_next_month", 0),
        },
        "alerts": alerts,
    }


# ---------------------------------------------------------------------
# Claude executive summary
# ---------------------------------------------------------------------

def write_summary(data: dict) -> str:
    try:
        import anthropic  # type: ignore
    except ImportError:
        return _fallback_summary(data)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_summary(data)
    client = anthropic.Anthropic(api_key=api_key)
    cfg = load_json(CONFIG_PATH)
    system = (
        "You are the in-house editor writing the weekly SEO recap for an "
        "affiliate site network. Be concrete, no fluff. Lead with the number "
        "that moved the most. End with a 3-item action list for next week."
    )
    user = (
        "Here's this week's data as JSON:\n\n"
        + json.dumps(data, indent=2)[:6000]
        + "\n\nWrite a 200-300 word executive recap. "
        "Sections: 1) Headline. 2) What moved. 3) Top 3 actions for next week. "
        "Plain HTML output, h2/p/ul only."
    )
    resp = client.messages.create(
        model=cfg.get("claude_model", "claude-sonnet-4-6"),
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def _fallback_summary(data: dict) -> str:
    return f"""
<h2>Headline</h2>
<p>{data['articles_published_count']} articles published this week across the
network. Estimated month-to-date revenue: ${data['revenue']['this_month']:,}.</p>
<h2>What moved</h2>
<p>Top 10 rankings: {data['rankings_summary'].get('top_10', 0)}.
Movers-up: {len(data['movers_up'])}.
Movers-down: {len(data['movers_down'])}.</p>
<h2>Next week — top 3 actions</h2>
<ul>
  <li>Refresh the top 3 page-2 keywords from this week's GSC pull.</li>
  <li>Add 2 internal links to each orphan article from link-builder.py.</li>
  <li>Run image-pipeline.py for any articles missing a hero image.</li>
</ul>
""".strip()


# ---------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------

def render_html(data: dict, summary_html: str) -> str:
    week = data["window_end"]
    rows_movers_up = "".join(
        f"<tr><td>{m.get('keyword','')}</td><td>{m.get('previous_position','—')}</td>"
        f"<td><strong>{m.get('current_position','—')}</strong></td>"
        f"<td class='up'>▲ {m.get('change','—')}</td></tr>"
        for m in data["movers_up"]
    ) or "<tr><td colspan='4' class='muted'>None this week.</td></tr>"
    rows_movers_down = "".join(
        f"<tr><td>{m.get('keyword','')}</td><td>{m.get('previous_position','—')}</td>"
        f"<td><strong>{m.get('current_position','—')}</strong></td>"
        f"<td class='down'>▼ {abs(m.get('change',0))}</td></tr>"
        for m in data["movers_down"]
    ) or "<tr><td colspan='4' class='muted'>None this week.</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><title>Weekly Report — {week}</title>
<style>
  body {{ font-family: -apple-system, Roboto, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1.5rem; color: #1a2332; }}
  h1, h2 {{ color: #2563eb; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: 0.6rem 0.85rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #f8fafc; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; }}
  .up {{ color: #10b981; font-weight: 700; }}
  .down {{ color: #ef4444; font-weight: 700; }}
  .muted {{ color: #94a3b8; }}
  .summary {{ background: #f8fafc; padding: 1.5rem; border-radius: 8px; }}
</style></head><body>
<h1>EmailToolAdviser — Weekly SEO Report</h1>
<p class="muted">Window: {data['window_start']} → {data['window_end']}</p>
<section class="summary">{summary_html}</section>
<h2>Top movers up</h2>
<table><thead><tr><th>Keyword</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead>
<tbody>{rows_movers_up}</tbody></table>
<h2>Top movers down</h2>
<table><thead><tr><th>Keyword</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead>
<tbody>{rows_movers_down}</tbody></table>
<h2>Articles published this week</h2>
<p>{data['articles_published_count']} total. By domain: {json.dumps(data['articles_by_domain'])}</p>
</body></html>"""


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = collect()
    summary_html = write_summary(data)
    html = render_html(data, summary_html)
    fname = f"weekly-{date.today().isoformat()}.html"
    out_path = REPORTS_DIR / fname
    out_path.write_text(html, encoding="utf-8")
    save_json(LATEST_REPORT, {
        "generated_at": now(),
        "report_path": f"/reports/{fname}",
        "headline": {
            "articles": data["articles_published_count"],
            "revenue": data["revenue"]["this_month"],
            "top_10": data["rankings_summary"].get("top_10", 0),
        },
        "summary_html": summary_html,
    })
    print(f"✓ Wrote {out_path}")
    print(f"✓ Latest summary at {LATEST_REPORT}")


if __name__ == "__main__":
    main()
