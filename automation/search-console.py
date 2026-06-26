#!/usr/bin/env python3
"""
search-console.py
=================

Submits new URLs to Google Search Console for indexing, verifies which
pages are indexed, surfaces indexing errors, and saves status to
data/indexing.json.

The actual "Request Indexing" button in GSC is gated to the Indexing API
(originally meant for JobPosting and BroadcastEvent — Google has tolerated
generic-page submissions from many sites). This script wraps both:

    --action submit-sitemap   → pings the Sitemaps API
    --action submit-urls      → calls the Indexing API (requires Indexing
                                  scope on the service account)
    --action inspect          → calls the URL Inspection API

Usage:
    python3 search-console.py --action submit-sitemap
    python3 search-console.py --action submit-urls --limit 10
    python3 search-console.py --action inspect --url https://emailtooladviser.com/

Install:
    pip install google-api-python-client google-auth
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
CREDENTIALS_PATH = THIS_DIR / "gsc-credentials.json"
PUBLISH_LOG_PATH = THIS_DIR / "publish-log.json"
INDEXING_PATH = SITE_ROOT / "data" / "indexing.json"

GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters"]
INDEXING_SCOPES = ["https://www.googleapis.com/auth/indexing"]


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_creds() -> None:
    if not CREDENTIALS_PATH.exists():
        sys.exit(
            f"Missing service account JSON at {CREDENTIALS_PATH}. "
            "See docs/setup-guide.md → Google Search Console setup."
        )


def gsc_client():
    ensure_creds()
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Install: pip install google-api-python-client google-auth")
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH), scopes=GSC_SCOPES,
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def indexing_client():
    ensure_creds()
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Install: pip install google-api-python-client google-auth")
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH), scopes=INDEXING_SCOPES,
    )
    return build("indexing", "v3", credentials=creds, cache_discovery=False)


def submit_sitemap(site: str, sitemap_url: str) -> None:
    svc = gsc_client()
    print(f"Submitting sitemap {sitemap_url} to {site}...")
    svc.sitemaps().submit(siteUrl=site, feedpath=sitemap_url).execute()
    print("Submitted.")


def submit_urls(limit: int) -> None:
    """Submit recently published URLs to the Indexing API."""
    log = load_json(PUBLISH_LOG_PATH) if PUBLISH_LOG_PATH.exists() else {"entries": []}
    state = load_json(INDEXING_PATH) if INDEXING_PATH.exists() else {
        "updated_at": utc_now(), "submitted": [], "indexed": [], "errors": []
    }
    submitted_urls = {s["url"] for s in state.get("submitted", [])}

    # Most-recent entries first, only ones not already submitted.
    entries = sorted(log.get("entries", []), key=lambda e: e.get("published_at", ""),
                     reverse=True)
    candidates = []
    for e in entries:
        url = e.get("url", "")
        # publish-log entries are stored as relative paths; convert to full.
        if url.startswith("/") and "domain" in e:
            url = f"https://{e['domain']}{url}"
        if url and url not in submitted_urls:
            candidates.append(url)
        if len(candidates) >= limit:
            break

    if not candidates:
        print("Nothing new to submit.")
        return

    svc = indexing_client()
    for url in candidates:
        body = {"url": url, "type": "URL_UPDATED"}
        try:
            svc.urlNotifications().publish(body=body).execute()
            state["submitted"].append({"url": url, "at": utc_now()})
            print(f"  ✓ Submitted {url}")
        except Exception as ex:  # noqa: BLE001
            state["errors"].append({"url": url, "error": str(ex), "at": utc_now()})
            print(f"  ✗ Error for {url}: {ex}")
    state["updated_at"] = utc_now()
    save_json(INDEXING_PATH, state)


def inspect_url(site: str, url: str) -> None:
    svc = gsc_client()
    request = {"inspectionUrl": url, "siteUrl": site, "languageCode": "en-US"}
    resp = svc.urlInspection().index().inspect(body=request).execute()
    print(json.dumps(resp, indent=2))

    # Update indexing.json with verdict.
    state = load_json(INDEXING_PATH) if INDEXING_PATH.exists() else {
        "updated_at": utc_now(), "submitted": [], "indexed": [], "errors": []
    }
    verdict = (resp.get("inspectionResult", {})
                   .get("indexStatusResult", {})
                   .get("verdict", "UNKNOWN"))
    record = {"url": url, "verdict": verdict, "at": utc_now()}
    if verdict == "PASS":
        state["indexed"].append(record)
    else:
        state["errors"].append(record)
    state["updated_at"] = utc_now()
    save_json(INDEXING_PATH, state)


def main():
    cfg = load_json(CONFIG_PATH)
    parser = argparse.ArgumentParser(description="Search Console actions.")
    parser.add_argument("--action", required=True,
                        choices=["submit-sitemap", "submit-urls", "inspect"])
    parser.add_argument("--site", default=None,
                        help="GSC property (defaults to https://<core_domain>/).")
    parser.add_argument("--sitemap", default=None,
                        help="Sitemap URL (defaults to https://<core_domain>/sitemap.xml).")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max URLs to submit per run.")
    parser.add_argument("--url", default=None, help="URL to inspect.")
    args = parser.parse_args()

    core = cfg["core_domain"]
    site = args.site or f"https://{core}/"
    sitemap_url = args.sitemap or f"https://{core}/sitemap.xml"

    if args.action == "submit-sitemap":
        submit_sitemap(site, sitemap_url)
    elif args.action == "submit-urls":
        submit_urls(args.limit)
    elif args.action == "inspect":
        if not args.url:
            sys.exit("--action inspect requires --url")
        inspect_url(site, args.url)


if __name__ == "__main__":
    main()
