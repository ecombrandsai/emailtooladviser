#!/usr/bin/env python3
"""
keyword-engine.py
=================

The keyword-discovery brain of the network. Expands seed keywords into
hundreds of candidates via Google Autocomplete + Search Console, scores
each on volume / competition / commercial intent / CPA alignment / content
gap, categorizes by funnel stage, and writes the top-500 ranked queue to
automation/keyword-queue.json.

Designed to be idempotent: re-running merges new candidates without
clobbering already-published keywords.

Usage:
    python3 automation/keyword-engine.py
    python3 automation/keyword-engine.py --refresh-from-gsc
    python3 automation/keyword-engine.py --dry-run

Requires (optional integrations):
    pip install google-api-python-client google-auth requests

Reads from env (all optional — script degrades gracefully if missing):
    GSC_SERVICE_ACCOUNT_JSON  (JSON string, for Search Console pulls)
    GOOGLE_API_KEY            (for Keyword Planner if you've enabled it)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
PUBLISH_LOG_PATH = THIS_DIR / "publish-log.json"


SEEDS = [
    "email marketing for small business",
    "best email marketing software",
    "Constant Contact review",
    "email marketing for local business",
    "email newsletter for small business",
    "email marketing tips",
    "how to do email marketing",
    "email marketing vs social media",
    "email marketing roi",
    "best email marketing for restaurants",
    "best email marketing for real estate",
    "best email marketing for gyms",
    "best email marketing for salons",
    "best email marketing for contractors",
    "best email marketing for dentists",
    "email marketing for beginners",
    "Constant Contact vs Mailchimp",
    "Constant Contact pricing",
    "email marketing platform comparison",
    "affordable email marketing small business",
]


# -----------------------------------------------------------------------------
# I/O
# -----------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(s: str) -> str:
    out = re.sub(r"[^a-z0-9\s-]", "", s.lower())
    return re.sub(r"[\s-]+", "-", out).strip("-")


# -----------------------------------------------------------------------------
# Discovery: Google Autocomplete
# -----------------------------------------------------------------------------

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search?client=firefox&q={q}"


def autocomplete(seed: str) -> list[str]:
    """Pull Google's public autocomplete suggestions for a seed."""
    try:
        url = AUTOCOMPLETE_URL.format(q=urllib.parse.quote_plus(seed))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
        return list(payload[1]) if len(payload) > 1 else []
    except Exception as e:  # noqa: BLE001
        print(f"  autocomplete failed for {seed!r}: {e}", file=sys.stderr)
        return []


def expand_seed(seed: str) -> list[str]:
    """Expand one seed via autocomplete on the seed itself plus letter-suffixed variants."""
    suggestions: set[str] = set()
    suggestions.update(autocomplete(seed))
    for c in "abcdefghijklmnopqrstuvwxyz":
        suggestions.update(autocomplete(f"{seed} {c}"))
    # Drop the seed itself if it bounced back.
    suggestions.discard(seed)
    return sorted(suggestions)


# -----------------------------------------------------------------------------
# Discovery: Google Search Console (existing keywords we already touch)
# -----------------------------------------------------------------------------

def gsc_keywords(site: str, days: int = 30) -> list[dict]:
    """Pull recent queries from GSC. Returns [{"keyword","clicks","impressions","position"}, ...]"""
    creds_blob = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not creds_blob:
        return []
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("Skipping GSC — install google-api-python-client", file=sys.stderr)
        return []

    creds_dict = json.loads(creds_blob)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query"],
        "rowLimit": 5000,
    }
    rows = svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])
    return [
        {
            "keyword": r["keys"][0],
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0)),
            "position": round(float(r.get("position", 0.0)), 1),
        }
        for r in rows
    ]


# -----------------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------------

COMMERCIAL_INTENT_WORDS = {
    "best", "review", "vs", "compare", "comparison", "alternative", "pricing",
    "cost", "buy", "deal", "discount", "for small business", "for local",
}
CPA_ALIGNED_WORDS = {
    "constant contact", "email marketing tool", "email marketing software",
    "email marketing platform", "best email marketing", "alternative to mailchimp",
    "newsletter platform", "email automation", "small business email",
}
INDUSTRY_WORDS = {
    "restaurant", "salon", "spa", "dentist", "doctor", "real estate",
    "contractor", "plumber", "electrician", "gym", "yoga", "florist",
    "bakery", "lawyer", "accountant", "nonprofit", "church",
}


def estimate_volume(kw: str, gsc_impressions: int | None) -> int:
    """Rough estimate. Prefer GSC impressions when present; otherwise heuristic by length and head terms."""
    if gsc_impressions and gsc_impressions > 0:
        return int(gsc_impressions * 4)  # GSC shows ours; market is wider
    head = ["best email marketing", "constant contact", "email marketing", "newsletter"]
    base = 100
    for h in head:
        if h in kw.lower():
            base = max(base, 800)
    words = len(kw.split())
    if words >= 5:
        base = int(base * 0.4)
    elif words == 4:
        base = int(base * 0.6)
    return base


def estimate_difficulty(kw: str, volume: int) -> str:
    if volume >= 5000:
        return "high"
    if volume >= 1500:
        return "medium"
    return "low"


def commercial_score(kw: str) -> int:
    s = sum(1 for w in COMMERCIAL_INTENT_WORDS if w in kw.lower())
    return min(s * 25, 100)


def cpa_score(kw: str) -> int:
    s = sum(1 for w in CPA_ALIGNED_WORDS if w in kw.lower())
    if "free" in kw.lower() and "email" in kw.lower():
        s += 1  # free-tool seekers convert too
    return min(s * 30, 100)


def gap_score(kw: str, published_urls: set[str]) -> int:
    slug = slugify(kw)
    for u in published_urls:
        if slug in u:
            return 0  # we already published
    return 100


def funnel(kw: str) -> str:
    k = kw.lower()
    if any(w in k for w in ["vs", "compare", "comparison", "review", "alternative"]):
        return "bottom_funnel"
    if any(w in k for w in ["best", "how to", "guide", "tutorial"]):
        return "mid_funnel"
    if any(w in k for w in INDUSTRY_WORDS):
        return "industry_specific"
    return "top_funnel"


def target_domain(kw: str) -> str:
    k = kw.lower()
    if any(w in k for w in INDUSTRY_WORDS) or "local" in k:
        return "smallbizemailhub.com"
    if "review" in k or "rating" in k:
        return "emailtoolratings.com" if "rating" in k else "emailtooladviser.com"
    if "compare" in k or "vs" in k or "comparison" in k:
        return "bestemailtoolreviews.com"
    if "best" in k and "rated" not in k:
        return "emailmarketingrated.com"
    return "emailtooladviser.com"


def suggested_title(kw: str) -> str:
    return " ".join(w.capitalize() for w in kw.split()) + " (2026)"


def score_keyword(kw: str, gsc_imp: int | None, published_urls: set[str]) -> dict:
    vol = estimate_volume(kw, gsc_imp)
    diff = estimate_difficulty(kw, vol)
    comm = commercial_score(kw)
    cpa = cpa_score(kw)
    gap = gap_score(kw, published_urls)
    # Combined priority: weighted average (volume 25%, comm 25%, cpa 25%, gap 25%; difficulty drags low)
    vol_score = min(vol / 200, 100)
    diff_drag = {"low": 100, "medium": 75, "high": 50}[diff]
    combined = (vol_score * 0.25 + comm * 0.25 + cpa * 0.25 + gap * 0.20 + diff_drag * 0.05)
    return {
        "keyword": kw,
        "monthly_volume": vol,
        "difficulty": diff,
        "intent": funnel(kw),
        "priority_score": round(combined, 1),
        "status": "pending" if gap == 100 else "published",
        "target_domain": target_domain(kw),
        "suggested_title": suggested_title(kw),
        "suggested_slug": slugify(kw),
        "cpa_alignment": round(cpa / 10),  # 0-10
        "published_date": None,
        "article_url": None,
    }


# -----------------------------------------------------------------------------
# Queue merge
# -----------------------------------------------------------------------------

def published_urls_from_log() -> set[str]:
    log = load_json(PUBLISH_LOG_PATH)
    return {e.get("url", "") for e in log.get("entries", [])}


def merge_into_queue(new_scored: list[dict]) -> dict:
    existing = load_json(QUEUE_PATH)
    keywords = existing.get("keywords", [])
    seen = {k.get("keyword", "").lower() for k in keywords}
    next_id = max((k.get("id", 0) for k in keywords), default=0) + 1
    added = 0
    for s in new_scored:
        if s["keyword"].lower() in seen:
            continue
        s["id"] = next_id
        next_id += 1
        keywords.append(s)
        added += 1
        seen.add(s["keyword"].lower())
    # Sort: pending first by priority_score desc; published at the bottom.
    keywords.sort(key=lambda k: (
        0 if k.get("status") == "pending" else 1,
        -float(k.get("priority_score", 0)),
    ))
    # Keep top 500 pending + all already-published.
    pending = [k for k in keywords if k.get("status") == "pending"][:500]
    done = [k for k in keywords if k.get("status") != "pending"]
    out = {"updated_at": now(), "keywords": pending + done}
    print(f"  added {added} new keywords; total queue = {len(out['keywords'])}")
    return out


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-from-gsc", action="store_true",
                        help="Also pull GSC queries from each domain.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)
    published_urls = published_urls_from_log()

    discovered: list[str] = []
    print(f"→ Expanding {len(SEEDS)} seeds via Google Autocomplete...")
    for seed in SEEDS:
        discovered.append(seed)
        discovered.extend(expand_seed(seed))

    # De-dupe
    discovered_unique = sorted({d.lower(): d for d in discovered}.values())
    print(f"  {len(discovered_unique)} unique candidates after dedup.")

    # Optionally enrich with GSC impressions
    gsc_map: dict[str, int] = {}
    if args.refresh_from_gsc:
        for domain in cfg.get("domains", []):
            site = f"https://{domain}/"
            print(f"  pulling GSC queries for {site}...")
            for row in gsc_keywords(site):
                gsc_map[row["keyword"].lower()] = row["impressions"]
                discovered_unique.append(row["keyword"])
        discovered_unique = sorted({d.lower(): d for d in discovered_unique}.values())

    print(f"→ Scoring {len(discovered_unique)} candidates...")
    scored = [
        score_keyword(kw, gsc_map.get(kw.lower()), published_urls)
        for kw in discovered_unique
    ]

    queue = merge_into_queue(scored)

    if args.dry_run:
        print("Dry run — not saving.")
        print(json.dumps(queue["keywords"][:5], indent=2))
        return

    save_json(QUEUE_PATH, queue)
    print(f"✓ Wrote {QUEUE_PATH}")


if __name__ == "__main__":
    main()
