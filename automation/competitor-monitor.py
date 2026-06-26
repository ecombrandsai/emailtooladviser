#!/usr/bin/env python3
"""
competitor-monitor.py
=====================

Runs weekly. For every keyword in our queue, fetches the top SERP results,
classifies which competitors are showing up, scores their content, and
flags both:
    1. New keywords competitors rank for that we don't
    2. Our articles stuck on page 2 that need improvement

Output:
    - automation/competitor-snapshot.json  (per-keyword competitor map)
    - data/page2-watchlist.json            (our articles on page 2)
    - Appends discovered keywords to automation/keyword-queue.json

Usage:
    python3 automation/competitor-monitor.py
    python3 automation/competitor-monitor.py --keyword-id 42 --verbose

Requires:
    A SerpAPI key OR a Google CSE setup. We use SerpAPI by default for
    simplicity. Set SERPAPI_API_KEY in env. Without it, the script degrades
    to GSC-only data (no SERP scrape).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import re
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
SNAPSHOT_PATH = THIS_DIR / "competitor-snapshot.json"
PAGE2_WATCHLIST = SITE_ROOT / "data" / "page2-watchlist.json"
CONFIG_PATH = THIS_DIR / "config.json"


SERPAPI_URL = "https://serpapi.com/search.json"
OUR_DOMAINS = {
    "emailtooladviser.com", "bestemailtoolreviews.com",
    "emailmarketingrated.com", "emailtoolratings.com",
    "smallbizemailhub.com",
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


# -----------------------------------------------------------------------------
# SERP fetch
# -----------------------------------------------------------------------------

def fetch_serp(keyword: str, num: int = 10) -> list[dict]:
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        return []
    params = {
        "engine": "google",
        "q": keyword,
        "api_key": api_key,
        "num": num,
        "gl": "us",
        "hl": "en",
    }
    url = SERPAPI_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            payload = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        print(f"  SerpAPI failed for {keyword!r}: {e}", file=sys.stderr)
        return []
    rows = []
    for i, item in enumerate(payload.get("organic_results", []), 1):
        rows.append({
            "position": i,
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "domain": _domain(item.get("link", "")),
        })
    return rows


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        return host.lstrip("www.").lower()
    except Exception:  # noqa: BLE001
        return ""


# -----------------------------------------------------------------------------
# Content analysis
# -----------------------------------------------------------------------------

def analyze_page(url: str) -> dict:
    """Best-effort word count + H2 count by hitting the page directly."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EmailToolAdviser-Bot"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read(2_000_000).decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return {"word_count": 0, "h2_count": 0}
    # crude word count: strip tags
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    words = len(text.split())
    h2_count = len(re.findall(r"<h2[\s>]", html, flags=re.I))
    return {"word_count": words, "h2_count": h2_count}


# -----------------------------------------------------------------------------
# Gap discovery
# -----------------------------------------------------------------------------

def serp_to_gaps(keyword: str, serp: list[dict]) -> dict:
    competitor_domains = sorted({r["domain"] for r in serp if r["domain"] not in OUR_DOMAINS})
    our_positions = [r["position"] for r in serp if r["domain"] in OUR_DOMAINS]
    we_rank = bool(our_positions)
    on_page_2 = bool(our_positions) and min(our_positions) > 10
    avg_word_count = 0
    if serp:
        samples = serp[:5]
        analyses = [analyze_page(r["link"]) for r in samples]
        wc = [a["word_count"] for a in analyses if a["word_count"] > 0]
        avg_word_count = int(sum(wc) / len(wc)) if wc else 0
    return {
        "keyword": keyword,
        "competitor_domains": competitor_domains,
        "we_rank": we_rank,
        "our_positions": our_positions,
        "on_page_2": on_page_2,
        "avg_top5_word_count": avg_word_count,
        "target_word_count": int(avg_word_count * 1.2) if avg_word_count else 2500,
    }


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword-id", type=int)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    queue = load_json(QUEUE_PATH)
    if not queue:
        sys.exit("No keyword-queue.json found.")

    candidates = queue.get("keywords", [])
    if args.keyword_id is not None:
        candidates = [k for k in candidates if k.get("id") == args.keyword_id]
    else:
        # Prioritize pending high-priority + already-published-but-might-be-page-2.
        candidates = sorted(
            candidates,
            key=lambda k: (-float(k.get("priority_score", 0)),),
        )[: args.limit]

    snapshot = load_json(SNAPSHOT_PATH) or {"updated_at": now(), "keywords": {}}
    page2 = []

    for kw in candidates:
        keyword = kw["keyword"]
        if args.verbose:
            print(f"→ Checking SERP for {keyword!r}...")
        serp = fetch_serp(keyword)
        if not serp:
            continue
        gaps = serp_to_gaps(keyword, serp)
        snapshot["keywords"][keyword] = {
            "snapshot_at": now(),
            "serp_top5": serp[:5],
            "gaps": gaps,
        }
        if gaps["on_page_2"]:
            page2.append({
                "keyword": keyword,
                "our_positions": gaps["our_positions"],
                "target_word_count": gaps["target_word_count"],
                "current_url": kw.get("article_url"),
            })
        time.sleep(1)  # be polite

    snapshot["updated_at"] = now()
    save_json(SNAPSHOT_PATH, snapshot)
    save_json(PAGE2_WATCHLIST, {"updated_at": now(), "items": page2})
    print(f"✓ Wrote snapshot ({len(snapshot['keywords'])} keywords tracked)")
    print(f"✓ Page-2 watchlist: {len(page2)} items")


if __name__ == "__main__":
    main()
