#!/usr/bin/env python3
"""
link-builder.py
===============

Maintains the internal-link graph across the network.

Modes:
    --map           Print the article graph (which page links to which)
    --orphans       Find pages with <3 incoming internal links
    --add-links     For each orphan, add 1-2 contextual links from related
                    articles (uses a topic-similarity heuristic + the
                    suggested-title from keyword-queue.json).
    --check-broken  Verify every internal link points to a real file.
    --vary-anchors  Re-distribute anchor text across satellite→core links
                    to avoid over-optimization patterns.

Usage:
    python3 automation/link-builder.py --map
    python3 automation/link-builder.py --orphans
    python3 automation/link-builder.py --add-links --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
GRAPH_PATH = SITE_ROOT / "data" / "link-graph.json"

EXCLUDE_DIRS = {"automation", "dashboard", "data", "reports", "docs", ".github"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def html_files() -> list[Path]:
    files = []
    for p in SITE_ROOT.rglob("*.html"):
        parts = p.relative_to(SITE_ROOT).parts
        if any(d in EXCLUDE_DIRS for d in parts):
            continue
        files.append(p)
    return sorted(files)


def rel_url_for(path: Path) -> str:
    rel = path.relative_to(SITE_ROOT).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[:-len("index.html")]
    return "/" + rel


def keyword_for(article_url: str, keywords: list[dict]) -> str:
    for k in keywords:
        if (k.get("article_url") or "").endswith(article_url) or (k.get("url") or "").endswith(article_url):
            return k.get("keyword", "")
    return ""


# ----------------------------------------------------------------------
# Graph build
# ----------------------------------------------------------------------

INTERNAL_LINK_RE = re.compile(r'href="(/[^"#?]+)"', flags=re.I)


def build_graph() -> dict:
    out = {"updated_at": now(), "nodes": [], "edges": []}
    keywords = load_json(QUEUE_PATH).get("keywords", [])
    files = html_files()
    in_count: dict[str, int] = defaultdict(int)
    out_count: dict[str, int] = defaultdict(int)

    pages = {}
    for f in files:
        url = rel_url_for(f)
        text = f.read_text(encoding="utf-8")
        outgoing = sorted({m for m in INTERNAL_LINK_RE.findall(text)
                           if not m.startswith("/automation/")
                           and not m.startswith("/data/")
                           and not m.startswith("/css/")
                           and not m.startswith("/js/")})
        pages[url] = {"path": str(f.relative_to(SITE_ROOT)), "outgoing": outgoing}
        out_count[url] = len(outgoing)
        for o in outgoing:
            in_count[o] += 1

    for url, meta in pages.items():
        out["nodes"].append({
            "url": url,
            "path": meta["path"],
            "keyword": keyword_for(url, keywords),
            "outgoing_count": out_count[url],
            "incoming_count": in_count[url],
        })
        for o in meta["outgoing"]:
            out["edges"].append({"from": url, "to": o})

    return out


# ----------------------------------------------------------------------
# Orphans
# ----------------------------------------------------------------------

def find_orphans(graph: dict, threshold: int = 3) -> list[dict]:
    return [n for n in graph["nodes"]
            if n["incoming_count"] < threshold and n["url"].startswith(("/articles/", "/comparisons/", "/reviews/"))]


# ----------------------------------------------------------------------
# Topic similarity (token-overlap heuristic)
# ----------------------------------------------------------------------

def token_set(s: str) -> set[str]:
    return set(re.findall(r"\w+", s.lower()))


def best_donors(orphan_node: dict, all_nodes: list[dict], k: int = 2) -> list[dict]:
    target_tokens = token_set(orphan_node.get("keyword", ""))
    if not target_tokens:
        return []
    scored = []
    for n in all_nodes:
        if n["url"] == orphan_node["url"]:
            continue
        if n["outgoing_count"] < 1:  # only fix pages that already have outbound links
            pass
        tokens = token_set(n.get("keyword", ""))
        overlap = len(target_tokens & tokens)
        if overlap >= 2:
            scored.append((overlap, n))
    scored.sort(reverse=True)
    return [n for _, n in scored[:k]]


# ----------------------------------------------------------------------
# Broken-link check
# ----------------------------------------------------------------------

def check_broken(graph: dict) -> list[dict]:
    valid = {n["url"] for n in graph["nodes"]}
    # also accept paths with .html stripped via _redirects
    broken = []
    for e in graph["edges"]:
        if e["to"] in valid:
            continue
        # try with .html appended
        if (e["to"].rstrip("/") + ".html") in valid:
            continue
        # external-looking? skip
        if e["to"].startswith("http"):
            continue
        broken.append(e)
    return broken


# ----------------------------------------------------------------------
# Add link: pick a sentence in donor page that contains common words, wrap it.
# ----------------------------------------------------------------------

def add_link_to_donor(donor_path: Path, orphan: dict, dry_run: bool) -> bool:
    text = donor_path.read_text(encoding="utf-8")
    # already linking?
    if f'href="{orphan["url"]}"' in text:
        return False

    # Find a sentence inside <p>...</p> that contains keyword tokens.
    target_tokens = token_set(orphan["keyword"])
    if not target_tokens:
        return False

    for m in re.finditer(r"<p>(.*?)</p>", text, flags=re.I | re.S):
        para = m.group(1)
        if "<a " in para:  # already has a link
            continue
        para_tokens = token_set(para)
        if len(target_tokens & para_tokens) >= 2:
            # Find a substring inside the para to wrap.
            anchor = orphan["keyword"]
            # Try to find the keyword phrase in para; if not, link the first
            # noun-like chunk.
            idx = para.lower().find(anchor.lower())
            if idx == -1:
                continue
            new_para = (
                para[:idx]
                + f'<a href="{orphan["url"]}">{para[idx:idx+len(anchor)]}</a>'
                + para[idx + len(anchor):]
            )
            new_text = text[:m.start(1)] + new_para + text[m.end(1):]
            if dry_run:
                print(f"    DRY: would add link from {donor_path} → {orphan['url']}")
                return True
            donor_path.write_text(new_text, encoding="utf-8")
            print(f"    ✓ added link from {donor_path.name} → {orphan['url']}")
            return True
    return False


# ----------------------------------------------------------------------
# Anchor variation (satellite → core)
# ----------------------------------------------------------------------

ANCHOR_VARIANTS = [
    "EmailToolAdviser",
    "our flagship review at EmailToolAdviser",
    "see our full review",
    "see our top pick",
    "our editorial review",
    "see how Constant Contact ranked",
    "read the complete review",
]


def vary_satellite_anchors() -> int:
    """Walk each satellite's HTML and randomize the anchor text on links to
    https://emailtooladviser.com. Returns number of files touched."""
    import random
    network = Path("/Users/tmurph/Desktop/emailtooladviser-network")
    touched = 0
    for sat in ("bestemailtoolreviews", "emailmarketingrated", "emailtoolratings", "smallbizemailhub"):
        for f in (network / sat).rglob("*.html"):
            text = f.read_text(encoding="utf-8")
            new = re.sub(
                r'<a href="https://emailtooladviser\.com"[^>]*>([^<]+)</a>',
                lambda m: f'<a href="https://emailtooladviser.com">{random.choice(ANCHOR_VARIANTS)}</a>',
                text,
            )
            if new != text:
                f.write_text(new, encoding="utf-8")
                touched += 1
    return touched


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", action="store_true")
    parser.add_argument("--orphans", action="store_true")
    parser.add_argument("--add-links", action="store_true")
    parser.add_argument("--check-broken", action="store_true")
    parser.add_argument("--vary-anchors", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not any([args.map, args.orphans, args.add_links, args.check_broken, args.vary_anchors]):
        args.map = True

    graph = build_graph()
    save_json(GRAPH_PATH, graph)

    if args.map:
        print(f"Graph: {len(graph['nodes'])} pages, {len(graph['edges'])} links.")
        for n in graph["nodes"]:
            print(f"  {n['url']:60s} in={n['incoming_count']:3d}  out={n['outgoing_count']:3d}")

    if args.orphans:
        orphans = find_orphans(graph)
        print(f"Orphans (incoming<3): {len(orphans)}")
        for o in orphans:
            print(f"  {o['url']}  incoming={o['incoming_count']}  kw={o.get('keyword','')!r}")

    if args.check_broken:
        broken = check_broken(graph)
        print(f"Broken internal links: {len(broken)}")
        for b in broken[:30]:
            print(f"  {b['from']} → {b['to']}")

    if args.vary_anchors:
        n = vary_satellite_anchors()
        print(f"Anchor-text varied across {n} satellite files.")

    if args.add_links:
        orphans = find_orphans(graph)
        added = 0
        for orphan in orphans:
            donors = best_donors(orphan, graph["nodes"])
            for d in donors:
                donor_path = SITE_ROOT / d["path"]
                if add_link_to_donor(donor_path, orphan, args.dry_run):
                    added += 1
                    if added >= 5:
                        break
        print(f"Added {added} internal links.")


if __name__ == "__main__":
    main()
