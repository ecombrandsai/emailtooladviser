#!/usr/bin/env python3
"""
dashboard-updater.py
====================

Recomputes every JSON file the dashboard reads. Runs every hour from the
master pipeline. Pulls GSC data when GSC_SERVICE_ACCOUNT_JSON is set.

Updates:
    data/rankings.json   from GSC (per domain)
    data/traffic.json    from GSC clicks (proxy for sessions until GA4 wired)
    data/revenue.json    from publish-log conversions × CPA × est_conv_rate
    data/content.json    counts of articles on disk per domain
    data/alerts.json     latest red/orange/green alerts

Usage:
    python3 automation/dashboard-updater.py
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
NETWORK_ROOT = SITE_ROOT.parent
PUBLISH_LOG = THIS_DIR / "publish-log.json"
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
CONFIG_PATH = THIS_DIR / "config.json"

RANKINGS = SITE_ROOT / "data" / "rankings.json"
TRAFFIC = SITE_ROOT / "data" / "traffic.json"
REVENUE = SITE_ROOT / "data" / "revenue.json"
CONTENT = SITE_ROOT / "data" / "content.json"
ALERTS = SITE_ROOT / "data" / "alerts.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(p: Path, d: dict | None = None) -> dict:
    if not p.exists():
        return d or {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------
# GSC pull (per-domain)
# ----------------------------------------------------------------------

def gsc_pull(site: str, days: int = 7) -> list[dict]:
    creds_blob = os.environ.get("GSC_SERVICE_ACCOUNT_JSON") or os.environ.get("GOOGLE_SERVICE_ACCOUNT")
    if not creds_blob:
        return []
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return []
    creds = service_account.Credentials.from_service_account_info(
        json.loads(creds_blob),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    end = date.today()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query"],
        "rowLimit": 5000,
    }
    try:
        rows = svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])
    except Exception as e:  # noqa: BLE001
        print(f"  GSC pull failed for {site}: {e}", file=sys.stderr)
        return []
    return [
        {
            "keyword": r["keys"][0],
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0)),
            "ctr": round(float(r.get("ctr", 0.0)) * 100, 2),
            "position": round(float(r.get("position", 0.0)), 1),
        }
        for r in rows
    ]


# ----------------------------------------------------------------------
# Content count (count HTML files per satellite + core)
# ----------------------------------------------------------------------

def count_content() -> dict:
    counts = {}
    for domain, dir_name in [
        ("emailtooladviser.com", "emailtooladviser"),
        ("bestemailtoolreviews.com", "bestemailtoolreviews"),
        ("emailmarketingrated.com", "emailmarketingrated"),
        ("emailtoolratings.com", "emailtoolratings"),
        ("smallbizemailhub.com", "smallbizemailhub"),
    ]:
        d = NETWORK_ROOT / dir_name
        if not d.exists():
            counts[domain] = {"articles_live": 0, "articles_this_week": 0, "next_scheduled_publish": None}
            continue
        # Only count items in articles/, comparisons/, reviews/.
        files = [
            f for sub in ("articles", "comparisons", "reviews")
            for f in (d / sub).rglob("*.html")
            if f.name != "index.html"
        ]
        counts[domain] = {
            "articles_live": len(files),
            "articles_this_week": _published_in_last(files, 7),
            "next_scheduled_publish": _next_06utc().isoformat(),
        }
    return counts


def _published_in_last(files: list[Path], days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    n = 0
    for f in files:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime >= cutoff:
            n += 1
    return n


def _next_06utc() -> datetime:
    n = datetime.now(timezone.utc)
    tgt = n.replace(hour=6, minute=0, second=0, microsecond=0)
    if tgt <= n:
        tgt += timedelta(days=1)
    return tgt


# ----------------------------------------------------------------------
# Revenue (estimated from clicks × estimated conversion rate × CPA)
# ----------------------------------------------------------------------

def estimate_revenue(content: dict, rankings: dict, cpa: int = 650,
                     conv_rate: float = 0.04) -> dict:
    # If we have GSC clicks per domain, use them; else fall back to 0.
    by_domain = {}
    total_clicks = 0
    for domain, dom_state in rankings.get("domains", {}).items():
        clicks = sum(k.get("clicks", 0) for k in dom_state.get("keywords", []))
        revenue = int(clicks * conv_rate * cpa)
        by_domain[domain] = {
            "clicks_30d": clicks,
            "conversions": int(clicks * conv_rate),
            "revenue": revenue,
        }
        total_clicks += clicks
    total_conv = int(total_clicks * conv_rate)
    return {
        "monthly_data": [],
        "total_lifetime": 0,
        "cpa_value": cpa,
        "estimated_conversion_rate": conv_rate,
        "this_month_conversions": total_conv,
        "this_month_revenue": total_conv * cpa,
        "last_month_conversions": 0,
        "last_month_revenue": 0,
        "mom_growth_pct": 0,
        "ytd_revenue": total_conv * cpa,
        "projected_next_month": int(total_conv * cpa * 1.15),
        "by_domain": by_domain,
        "last_updated": now(),
    }


# ----------------------------------------------------------------------
# Rankings rollup
# ----------------------------------------------------------------------

def build_rankings(cfg: dict) -> dict:
    out = {
        "keywords": [],
        "last_updated": now(),
        "domains": {},
        "summary": {"top_3": 0, "top_10": 0, "top_100": 0,
                    "new_this_week": 0, "positions_gained": 0, "positions_lost": 0},
        "movers_up": [],
        "movers_down": [],
        "new_entries": [],
    }
    for domain in cfg.get("domains", []):
        site_url = f"https://{domain}/"
        kws = gsc_pull(site_url, days=7)
        top_3 = sum(1 for k in kws if 0 < k["position"] <= 3)
        top_10 = sum(1 for k in kws if 0 < k["position"] <= 10)
        top_100 = sum(1 for k in kws if 0 < k["position"] <= 100)
        key = domain.split(".")[0]
        out["domains"][key] = {"keywords": kws, "top_3": top_3, "top_10": top_10, "top_100": top_100}
        out["summary"]["top_3"] += top_3
        out["summary"]["top_10"] += top_10
        out["summary"]["top_100"] += top_100
        out["keywords"].extend({"domain": domain, **k} for k in kws)
    return out


# ----------------------------------------------------------------------
# Traffic (use clicks as proxy until GA4 is wired)
# ----------------------------------------------------------------------

def build_traffic(rankings: dict) -> dict:
    out = {
        "updated_at": now(),
        "domains": {},
        "totals": {"today": 0, "this_week": 0, "this_month": 0, "wow_growth_pct": 0},
    }
    for domain_full in ("emailtooladviser.com", "bestemailtoolreviews.com",
                         "emailmarketingrated.com", "emailtoolratings.com",
                         "smallbizemailhub.com"):
        key = domain_full.split(".")[0]
        kws = rankings.get("domains", {}).get(key, {}).get("keywords", [])
        clicks_week = sum(k.get("clicks", 0) for k in kws)
        out["domains"][domain_full] = {
            "today": clicks_week // 7,
            "this_week": clicks_week,
            "this_month": clicks_week * 4,
            "last_month": 0,
        }
        out["totals"]["today"] += clicks_week // 7
        out["totals"]["this_week"] += clicks_week
        out["totals"]["this_month"] += clicks_week * 4
    return out


# ----------------------------------------------------------------------
# Alerts
# ----------------------------------------------------------------------

def compute_alerts(content: dict, rankings: dict, revenue: dict) -> dict:
    red, orange, green = [], [], []
    # Red: any domain with 0 articles this week
    for dom, c in content.items():
        if c["articles_live"] > 0 and c["articles_this_week"] == 0:
            red.append({"type": "no_publish_this_week", "domain": dom,
                        "msg": f"No new articles in {dom} this week."})
    # Orange: page 2 keywords
    for k in rankings.get("keywords", []):
        if 10 < k.get("position", 0) <= 20 and k.get("impressions", 0) >= 100:
            orange.append({"type": "page_2_keyword", "keyword": k["keyword"],
                            "domain": k["domain"], "position": k["position"]})
    # Green: top-10 entries
    for k in rankings.get("keywords", []):
        if 0 < k.get("position", 0) <= 10:
            green.append({"type": "top10", "keyword": k["keyword"],
                          "position": k["position"], "domain": k["domain"]})
    return {
        "updated_at": now(),
        "red": red[:10],
        "orange": orange[:10],
        "green": green[:10],
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    cfg = load_json(CONFIG_PATH, {"domains": [
        "emailtooladviser.com", "bestemailtoolreviews.com", "emailmarketingrated.com",
        "emailtoolratings.com", "smallbizemailhub.com",
    ]})
    rankings = build_rankings(cfg)
    save_json(RANKINGS, rankings)
    traffic = build_traffic(rankings)
    save_json(TRAFFIC, traffic)
    content_counts = count_content()
    queue = load_json(QUEUE_PATH)
    pending = sum(1 for k in queue.get("keywords", []) if k.get("status") in ("pending", "unpublished"))
    total_live = sum(c["articles_live"] for c in content_counts.values())
    save_json(CONTENT, {
        "articles": [],
        "total_published": total_live,
        "queue_size": pending,
        "last_generated": now(),
        "next_scheduled": _next_06utc().isoformat(),
        "domains": content_counts,
        "totals": {
            "articles_live": total_live,
            "articles_in_queue": pending,
            "articles_published_this_week": sum(c["articles_this_week"] for c in content_counts.values()),
            "days_of_content_queued_at_current_pace": pending // 15 if pending else 0,
        },
    })
    revenue = estimate_revenue(content_counts, rankings, cpa=cfg.get("cpa_value", 650))
    save_json(REVENUE, revenue)
    save_json(ALERTS, compute_alerts(content_counts, rankings, revenue))
    print("✓ Dashboard data refreshed.")


if __name__ == "__main__":
    main()
