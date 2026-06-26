#!/usr/bin/env python3
"""
authority-builder.py
====================

Tracks domain-authority signals over time and surfaces the things you can
actually do to move them up.

What it covers:
    --velocity      Reports articles published per week per domain; flags
                    domains that fall behind the 3-per-day schedule.
    --social-posts  Drafts shareable LinkedIn/X posts for each recently
                    published article (uses Claude). Persists to
                    data/social-queue.json.
    --citations     Maintains an NAP-consistent citation list across
                    business directories (data/citations.json).
    --report        Prints a one-screen authority dashboard.

Usage:
    python3 automation/authority-builder.py --velocity
    python3 automation/authority-builder.py --social-posts --limit 5
    python3 automation/authority-builder.py --citations
    python3 automation/authority-builder.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
NETWORK_ROOT = SITE_ROOT.parent
PUBLISH_LOG_PATH = THIS_DIR / "publish-log.json"
SOCIAL_QUEUE = SITE_ROOT / "data" / "social-queue.json"
CITATIONS = SITE_ROOT / "data" / "citations.json"
CONFIG_PATH = THIS_DIR / "config.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ----------------------------------------------------------------------
# Velocity
# ----------------------------------------------------------------------

def report_velocity() -> dict:
    log = load_json(PUBLISH_LOG_PATH, {"entries": []})
    by_domain_week: dict[str, list[int]] = defaultdict(list)
    today = date.today()
    weeks_back = 4
    cutoff = today - timedelta(days=7 * weeks_back)

    by_domain_count: dict[str, int] = defaultdict(int)
    for e in log["entries"]:
        published = e.get("published_at", "")[:10]
        if not published:
            continue
        try:
            d = date.fromisoformat(published)
        except ValueError:
            continue
        if d < cutoff:
            continue
        by_domain_count[e.get("domain", "unknown")] += 1

    out = {"updated_at": now(), "weeks_window": weeks_back, "per_domain": {}}
    target_per_4w = 3 * 7 * weeks_back  # 3 per day × 7 days × N weeks
    for domain, count in by_domain_count.items():
        out["per_domain"][domain] = {
            "published_last_4w": count,
            "target_last_4w": target_per_4w,
            "pct_of_target": round(count / target_per_4w * 100, 1) if target_per_4w else 0,
            "status": "on_track" if count >= target_per_4w * 0.9 else "behind",
        }
    return out


# ----------------------------------------------------------------------
# Social drafting
# ----------------------------------------------------------------------

def draft_social_posts(limit: int) -> None:
    try:
        import anthropic  # type: ignore
    except ImportError:
        sys.exit("pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY env var required.")
    cfg = load_json(CONFIG_PATH)
    log = load_json(PUBLISH_LOG_PATH, {"entries": []})
    queue = load_json(SOCIAL_QUEUE, {"posts": []})
    already_drafted = {p["url"] for p in queue["posts"]}
    candidates = [e for e in log["entries"]
                  if e.get("url") and e["url"] not in already_drafted]
    candidates.sort(key=lambda e: e.get("published_at", ""), reverse=True)
    candidates = candidates[:limit]
    if not candidates:
        print("Nothing new to draft.")
        return

    client = anthropic.Anthropic(api_key=api_key)
    for entry in candidates:
        url = entry["url"]
        keyword = entry.get("keyword_id", "")
        system = (
            "You write concise, value-first social posts that don't smell like marketing. "
            "Lead with a specific number or surprising fact, then a hook, then the link. "
            "Never use hashtag spam. 2-3 hashtags max."
        )
        user = f"""
Draft two posts for our newly published article: {url}

Format:
LinkedIn: (3-4 sentences, professional tone, hook + insight + link)
---
X / Twitter: (under 270 chars, single sharp hook + link)

Output only the two posts in the format above. Nothing else.
"""
        resp = client.messages.create(
            model=cfg.get("claude_model", "claude-sonnet-4-6"),
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        queue["posts"].append({
            "url": url,
            "drafted_at": now(),
            "content": txt,
            "posted": False,
        })
        print(f"  ✓ drafted social posts for {url}")
    queue["updated_at"] = now()
    save_json(SOCIAL_QUEUE, queue)


# ----------------------------------------------------------------------
# Citations
# ----------------------------------------------------------------------

CITATION_SITES = [
    "Google Business Profile", "Bing Places", "Yelp", "Yellow Pages",
    "Foursquare", "Apple Maps", "Crunchbase", "LinkedIn Company",
    "Better Business Bureau", "Manta", "Hotfrog", "Brownbook",
]


def init_citations(cfg: dict) -> dict:
    state = load_json(CITATIONS, {"nap": {}, "submissions": []})
    if not state.get("nap"):
        state["nap"] = {
            "name": cfg.get("site_name", "EmailToolAdviser"),
            "tagline": cfg.get("site_tagline", ""),
            "website": cfg.get("core_domain", "https://emailtooladviser.com"),
            "email": "hello@emailtooladviser.com",
        }
    by_name = {s["name"] for s in state["submissions"]}
    next_id = max((s["id"] for s in state["submissions"]), default=0) + 1
    for site in CITATION_SITES:
        if site in by_name:
            continue
        state["submissions"].append({
            "id": next_id, "name": site, "status": "pending",
            "submitted_at": None, "url": None,
        })
        next_id += 1
    state["updated_at"] = now()
    save_json(CITATIONS, state)
    return state


# ----------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------

def report() -> None:
    print("=" * 60)
    print("EmailToolAdviser — Authority report")
    print(f"Generated: {now()}")
    print("=" * 60)
    v = report_velocity()
    print("\nContent velocity (last 4 weeks):")
    for domain, m in v["per_domain"].items():
        print(f"  {domain:36s}  {m['published_last_4w']:4d}/{m['target_last_4w']}  {m['status']}")
    queue = load_json(SOCIAL_QUEUE, {"posts": []})
    print(f"\nSocial posts drafted (not yet posted): {sum(1 for p in queue['posts'] if not p['posted'])}")
    citations = load_json(CITATIONS, {"submissions": []})
    by_status = defaultdict(int)
    for s in citations.get("submissions", []):
        by_status[s.get("status", "pending")] += 1
    print(f"\nCitations: pending={by_status['pending']}  submitted={by_status['submitted']}  verified={by_status['verified']}")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--velocity", action="store_true")
    parser.add_argument("--social-posts", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--citations", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)

    if args.velocity:
        print(json.dumps(report_velocity(), indent=2))
    if args.social_posts:
        draft_social_posts(args.limit)
    if args.citations:
        init_citations(cfg)
        print(f"Initialized citations queue ({len(CITATION_SITES)} sites).")
    if args.report:
        report()


if __name__ == "__main__":
    main()
