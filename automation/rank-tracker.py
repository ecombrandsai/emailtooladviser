#!/usr/bin/env python3
"""
rank-tracker.py
===============

Pulls 90 days of search analytics from Google Search Console for the
configured property, compares this week to the previous week, surfaces
movers up/down and new entries, persists the summary to
data/rankings.json, and writes an HTML weekly report to
reports/weekly-report.html.

Requires service account credentials JSON at automation/gsc-credentials.json
with read access to the GSC property listed in --site.

Usage:
    python3 rank-tracker.py --site https://emailtooladviser.com/
    python3 rank-tracker.py --site sc-domain:emailtooladviser.com --days 90
    python3 rank-tracker.py --email-report

Install:
    pip install google-api-python-client google-auth
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
CREDENTIALS_PATH = THIS_DIR / "gsc-credentials.json"
RANKINGS_PATH = SITE_ROOT / "data" / "rankings.json"
REPORT_PATH = SITE_ROOT / "reports" / "weekly-report.html"

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
DEFAULT_DAYS = 90


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def gsc_client():
    if not CREDENTIALS_PATH.exists():
        sys.exit(
            "Missing GSC credentials. Place a service-account JSON at\n"
            f"  {CREDENTIALS_PATH}\n"
            "and add the service account email as an owner in Google Search Console."
        )
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Install: pip install google-api-python-client google-auth")
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH), scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def fetch_search_analytics(svc, site: str, start: date, end: date,
                           dimensions: list[str]) -> list[dict]:
    request = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimensions,
        "rowLimit": 25000,
        "dataState": "all",
    }
    resp = svc.searchanalytics().query(siteUrl=site, body=request).execute()
    return resp.get("rows", [])


def keyword_table(rows: list[dict]) -> dict[str, dict]:
    """Map keyword -> {clicks, impressions, ctr, position}"""
    out: dict[str, dict] = {}
    for r in rows:
        if not r.get("keys"):
            continue
        kw = r["keys"][0]
        out[kw] = {
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0)),
            "ctr": round(float(r.get("ctr", 0.0)) * 100, 2),
            "position": round(float(r.get("position", 0.0)), 1),
        }
    return out


def compute_diff(current: dict[str, dict], previous: dict[str, dict],
                 threshold: int) -> dict:
    movers_up, movers_down, new_entries = [], [], []
    for kw, cur in current.items():
        prev = previous.get(kw)
        if prev is None:
            new_entries.append({
                "keyword": kw,
                "position": cur["position"],
                "clicks": cur["clicks"],
                "impressions": cur["impressions"],
            })
            continue
        # GSC position: lower number is better, so improvement = previous - current
        change = round(prev["position"] - cur["position"], 1)
        if change >= threshold:
            movers_up.append({
                "keyword": kw,
                "previous_position": prev["position"],
                "current_position": cur["position"],
                "change": change,
            })
        elif change <= -threshold:
            movers_down.append({
                "keyword": kw,
                "previous_position": prev["position"],
                "current_position": cur["position"],
                "change": change,
            })

    movers_up.sort(key=lambda x: x["change"], reverse=True)
    movers_down.sort(key=lambda x: x["change"])
    new_entries.sort(key=lambda x: x["clicks"], reverse=True)

    return {
        "movers_up": movers_up,
        "movers_down": movers_down,
        "new_entries": new_entries,
    }


def summarize(current: dict[str, dict]) -> dict:
    top_3 = sum(1 for v in current.values() if 0 < v["position"] <= 3)
    top_10 = sum(1 for v in current.values() if 0 < v["position"] <= 10)
    top_100 = sum(1 for v in current.values() if 0 < v["position"] <= 100)
    return {"top_3": top_3, "top_10": top_10, "top_100": top_100}


def write_report(summary: dict, diff: dict, current: dict[str, dict]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    movers_up_rows = "\n".join([
        f"<tr><td>{m['keyword']}</td><td>{m['previous_position']}</td>"
        f"<td><strong>{m['current_position']}</strong></td>"
        f"<td class='up'>▲ {m['change']}</td></tr>"
        for m in diff["movers_up"][:20]
    ]) or "<tr><td colspan='4' class='muted'>No movers up this week.</td></tr>"

    movers_down_rows = "\n".join([
        f"<tr><td>{m['keyword']}</td><td>{m['previous_position']}</td>"
        f"<td><strong>{m['current_position']}</strong></td>"
        f"<td class='down'>▼ {abs(m['change'])}</td></tr>"
        for m in diff["movers_down"][:20]
    ]) or "<tr><td colspan='4' class='muted'>No movers down this week.</td></tr>"

    new_entry_rows = "\n".join([
        f"<tr><td>{e['keyword']}</td><td>{e['position']}</td>"
        f"<td>{e['clicks']}</td><td>{e['impressions']}</td></tr>"
        for e in diff["new_entries"][:20]
    ]) or "<tr><td colspan='4' class='muted'>No new entries this week.</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><title>Weekly Report — {today}</title>
<style>
  body {{ font-family: -apple-system, Roboto, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1.5rem; color: #1a2332; }}
  h1, h2 {{ color: #2563eb; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #f8fafc; font-size: 0.85rem; text-transform: uppercase; }}
  .summary {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin: 1rem 0; }}
  .card {{ background: #f8fafc; padding: 1rem; border-radius: 6px; }}
  .card .label {{ font-size: 0.8rem; color: #64748b; text-transform: uppercase; }}
  .card .value {{ font-size: 2rem; font-weight: 700; color: #2563eb; }}
  .up {{ color: #10b981; font-weight: 700; }}
  .down {{ color: #ef4444; font-weight: 700; }}
  .muted {{ color: #94a3b8; }}
</style></head><body>
<h1>EmailToolAdviser Weekly Ranking Report</h1>
<p>{today}</p>
<div class="summary">
  <div class="card"><div class="label">Top 3</div><div class="value">{summary['top_3']}</div></div>
  <div class="card"><div class="label">Top 10</div><div class="value">{summary['top_10']}</div></div>
  <div class="card"><div class="label">Top 100</div><div class="value">{summary['top_100']}</div></div>
</div>
<h2>Top movers up</h2>
<table><thead><tr><th>Keyword</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead><tbody>{movers_up_rows}</tbody></table>
<h2>Top movers down</h2>
<table><thead><tr><th>Keyword</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead><tbody>{movers_down_rows}</tbody></table>
<h2>New entries in top 100</h2>
<table><thead><tr><th>Keyword</th><th>Position</th><th>Clicks</th><th>Impressions</th></tr></thead><tbody>{new_entry_rows}</tbody></table>
<p style="margin-top:2rem;color:#94a3b8;font-size:0.85rem;">Generated by rank-tracker.py · Data via Google Search Console</p>
</body></html>"""
    REPORT_PATH.write_text(html, encoding="utf-8")


def send_email_report(cfg: dict, summary: dict) -> None:
    smtp = cfg.get("smtp", {})
    host = smtp.get("host")
    if not host:
        print("SMTP not configured in config.json — skipping email.")
        return
    msg = EmailMessage()
    msg["Subject"] = f"EmailToolAdviser weekly report — top10: {summary['top_10']}, top3: {summary['top_3']}"
    msg["From"] = smtp.get("from", "reports@emailtooladviser.com")
    msg["To"] = smtp.get("to", "")
    msg.set_content("See attached HTML weekly report.")
    if REPORT_PATH.exists():
        msg.add_attachment(
            REPORT_PATH.read_bytes(),
            maintype="text", subtype="html",
            filename="weekly-report.html",
        )
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, smtp.get("port", 587)) as server:
        server.starttls(context=ctx)
        if smtp.get("user"):
            server.login(smtp["user"], smtp.get("password", ""))
        server.send_message(msg)
    print(f"Email sent to {msg['To']}")


def main():
    parser = argparse.ArgumentParser(description="Track GSC rankings.")
    parser.add_argument("--site", required=False, default=None,
                        help="GSC property URL or sc-domain:... (default: core domain).")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--threshold", type=int, default=3,
                        help="Position change required to count as a mover.")
    parser.add_argument("--email-report", action="store_true",
                        help="Send the report via SMTP.")
    args = parser.parse_args()

    cfg = load_config()
    site = args.site or f"https://{cfg['core_domain']}/"

    svc = gsc_client()

    end = date.today()
    start = end - timedelta(days=args.days)
    mid = end - timedelta(days=7)
    prev_start = mid - timedelta(days=7)

    print(f"Fetching {site} {prev_start} → {end} ...")
    current = keyword_table(fetch_search_analytics(svc, site, mid, end, ["query"]))
    previous = keyword_table(fetch_search_analytics(svc, site, prev_start, mid, ["query"]))

    diff = compute_diff(current, previous, args.threshold)
    summary = summarize(current)
    summary["new_this_week"] = len(diff["new_entries"])
    summary["positions_gained"] = sum(m["change"] for m in diff["movers_up"])
    summary["positions_lost"] = sum(abs(m["change"]) for m in diff["movers_down"])

    snapshot = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "keywords": [{"keyword": k, **v} for k, v in current.items()],
        "movers_up": diff["movers_up"][:50],
        "movers_down": diff["movers_down"][:50],
        "new_entries": diff["new_entries"][:50],
    }
    save_json(RANKINGS_PATH, snapshot)
    print(f"Wrote {RANKINGS_PATH}")
    write_report(summary, diff, current)
    print(f"Wrote {REPORT_PATH}")

    if args.email_report:
        send_email_report(cfg, summary)


if __name__ == "__main__":
    main()
