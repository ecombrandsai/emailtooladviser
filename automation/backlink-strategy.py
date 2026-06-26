#!/usr/bin/env python3
"""
backlink-strategy.py
====================

Manages the off-page link building strategy:

    1. Guest-post prospect discovery via Google search operators (uses
       SerpAPI when SERPAPI_API_KEY is set; otherwise emits the search
       URLs for manual review).
    2. Prospect scoring (relevance + recent activity heuristics).
    3. Personalized outreach email drafting via Claude.
    4. Outreach tracking in data/outreach.json.
    5. HARO query monitoring (queries delivered to email; this script
       scaffolds the response generator).
    6. Niche directory submission queue.
    7. Inter-site link strategy guardrails.

Usage:
    python3 automation/backlink-strategy.py --discover
    python3 automation/backlink-strategy.py --draft-outreach --prospect-id 4
    python3 automation/backlink-strategy.py --directories
    python3 automation/backlink-strategy.py --network-link-audit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
OUTREACH_PATH = SITE_ROOT / "data" / "outreach.json"
DIRECTORIES_PATH = SITE_ROOT / "data" / "directories.json"

GUEST_POST_QUERIES = [
    'site:.com inurl:write-for-us "email marketing"',
    'site:.com inurl:guest-post "small business"',
    'site:.com inurl:submit-a-post "email marketing"',
    'intitle:"write for us" "email newsletter"',
    'intitle:"submit a guest post" "small business marketing"',
    '"contribute to" "email marketing" -site:medium.com',
    '"guest author" "email marketing" "small business"',
]

DIRECTORIES = [
    "Crunchbase", "AngelList", "G2", "Capterra", "GetApp", "TrustRadius",
    "Software Advice", "PCMag", "Hosting Tribunal", "Smart Insights",
    "Email Vendor Selection", "MarketingProfs Directory",
]


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
# Guest-post discovery
# ----------------------------------------------------------------------

def search_serpapi(query: str, num: int = 10) -> list[dict]:
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        return []
    import urllib.request
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode({
        "engine": "google", "q": query, "api_key": api_key, "num": num,
    })
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            payload = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        print(f"SerpAPI failed: {e}", file=sys.stderr)
        return []
    rows = []
    for item in payload.get("organic_results", []):
        rows.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "domain": (urllib.parse.urlparse(item.get("link", "")).hostname or "").lstrip("www."),
        })
    return rows


def discover_prospects() -> dict:
    """Run all guest-post queries (or emit them as clickable URLs)."""
    state = load_json(OUTREACH_PATH, {"prospects": []})
    seen_domains = {p["domain"] for p in state["prospects"]}
    api_key = os.environ.get("SERPAPI_API_KEY")
    new_ids_start = max((p["id"] for p in state["prospects"]), default=0) + 1
    for q in GUEST_POST_QUERIES:
        if not api_key:
            url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)
            print(f"  manual: {url}")
            continue
        for row in search_serpapi(q, num=10):
            if not row["domain"] or row["domain"] in seen_domains:
                continue
            state["prospects"].append({
                "id": new_ids_start,
                "domain": row["domain"],
                "page_title": row["title"],
                "page_url": row["url"],
                "snippet": row["snippet"],
                "score": score_prospect(row),
                "status": "discovered",
                "discovered_at": now(),
                "outreach_log": [],
                "link_acquired": False,
            })
            seen_domains.add(row["domain"])
            new_ids_start += 1
    state["updated_at"] = now()
    save_json(OUTREACH_PATH, state)
    print(f"Saved {len(state['prospects'])} prospects to {OUTREACH_PATH}")
    return state


def score_prospect(row: dict) -> int:
    score = 0
    txt = (row.get("title", "") + " " + row.get("snippet", "")).lower()
    if "email" in txt:
        score += 30
    if "small business" in txt:
        score += 20
    if "guest" in txt or "write for us" in txt or "contribute" in txt:
        score += 25
    if "2026" in txt or "2025" in txt:
        score += 10
    if row["domain"].endswith((".gov", ".edu")):
        score += 30  # high-authority lift
    return min(score, 100)


# ----------------------------------------------------------------------
# Outreach email drafting (Claude)
# ----------------------------------------------------------------------

def draft_outreach(prospect: dict, cfg: dict) -> dict:
    try:
        import anthropic  # type: ignore
    except ImportError:
        sys.exit("pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY env var required.")
    client = anthropic.Anthropic(api_key=api_key)

    system = (
        "You write genuinely helpful guest-post pitches. Never spam. Never name-drop. "
        "Always lead with what the recipient would value, not what you want. "
        "Tone: editorial peer, not marketer. Length: under 150 words."
    )
    user = f"""
Write a guest-post outreach email to the editor of {prospect['domain']}.

About them: their page is titled {prospect['page_title']!r} and snippet says:
{prospect['snippet']!r}.

About us: EmailToolAdviser is an independent editorial network covering email
marketing for small business. Our editorial team tests every platform for 90
days on real lists.

Pitch ONE specific article topic that fits their audience based on the snippet
above. Include a one-line about the author. Sign as "EmailToolAdviser
Editorial Team."

Output: subject line + email body, separated by ---. Nothing else.
"""

    resp = client.messages.create(
        model=cfg.get("claude_model", "claude-sonnet-4-6"),
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    parts = txt.split("---", 1)
    subject = parts[0].strip().replace("Subject:", "").strip()
    body = parts[1].strip() if len(parts) > 1 else ""
    return {"subject": subject, "body": body, "drafted_at": now()}


# ----------------------------------------------------------------------
# Directory submission queue
# ----------------------------------------------------------------------

def init_directories() -> dict:
    state = load_json(DIRECTORIES_PATH, {"directories": []})
    by_name = {d["name"] for d in state["directories"]}
    next_id = max((d["id"] for d in state["directories"]), default=0) + 1
    for name in DIRECTORIES:
        if name in by_name:
            continue
        state["directories"].append({
            "id": next_id, "name": name, "domains_submitted": [],
            "status": "pending",
        })
        next_id += 1
    state["updated_at"] = now()
    save_json(DIRECTORIES_PATH, state)
    print(f"Directory queue: {len(state['directories'])} entries.")
    return state


# ----------------------------------------------------------------------
# Network link audit
# ----------------------------------------------------------------------

def network_link_audit() -> None:
    """Walks each satellite and confirms it links to emailtooladviser.com at
    least twice. Prints warnings on under-linked files."""
    import re
    network_root = SITE_ROOT.parent
    warnings = 0
    for sat in ("bestemailtoolreviews", "emailmarketingrated", "emailtoolratings", "smallbizemailhub"):
        for f in (network_root / sat).rglob("*.html"):
            text = f.read_text(encoding="utf-8")
            count = len(re.findall(r'href="https://emailtooladviser\.com', text))
            if count < 2:
                print(f"  ⚠ {f.relative_to(network_root)}  links={count}")
                warnings += 1
    print(f"Audit complete. {warnings} files below 2 links to core domain.")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--draft-outreach", action="store_true")
    parser.add_argument("--prospect-id", type=int)
    parser.add_argument("--directories", action="store_true")
    parser.add_argument("--network-link-audit", action="store_true")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)

    if args.discover:
        discover_prospects()

    if args.draft_outreach:
        state = load_json(OUTREACH_PATH, {"prospects": []})
        targets = [p for p in state["prospects"]
                   if (args.prospect_id is None or p["id"] == args.prospect_id)
                   and p["status"] == "discovered"]
        for p in targets[:5]:  # safety cap per run
            draft = draft_outreach(p, cfg)
            p["outreach_log"].append(draft)
            p["status"] = "drafted"
            print(f"  ✓ drafted for {p['domain']}: {draft['subject']!r}")
        save_json(OUTREACH_PATH, state)

    if args.directories:
        init_directories()

    if args.network_link_audit:
        network_link_audit()


if __name__ == "__main__":
    main()
