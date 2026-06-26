#!/usr/bin/env python3
"""
google-apis.py
==============

Single source of truth for every Google API call the network makes. Every
other automation script imports from here so we only patch credentials
and base URLs in one place.

Supported APIs:
    - Google Search Console v1 (search-analytics, sitemaps, URL inspection)
    - Google Trends (via the public-facing trending endpoint — unofficial,
      best-effort)
    - Google Autocomplete (public suggest endpoint)
    - Google Keyword Planner via Ads API (stubbed — requires OAuth + a
      developer token; populated when GOOGLE_ADS_DEVELOPER_TOKEN is set)

Environment variables:
    GSC_SERVICE_ACCOUNT_JSON       — raw JSON for the service account
    GOOGLE_ADS_DEVELOPER_TOKEN     — Google Ads dev token (Keyword Planner)
    GOOGLE_ADS_CLIENT_ID           — OAuth client id
    GOOGLE_ADS_CLIENT_SECRET       — OAuth client secret
    GOOGLE_ADS_REFRESH_TOKEN       — OAuth refresh token
    GOOGLE_ADS_LOGIN_CUSTOMER_ID   — manager account id (no dashes)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta


# -----------------------------------------------------------------------------
# Google Search Console
# -----------------------------------------------------------------------------

GSC_SCOPES_READ = ["https://www.googleapis.com/auth/webmasters.readonly"]
GSC_SCOPES_RW = ["https://www.googleapis.com/auth/webmasters"]
INDEXING_SCOPES = ["https://www.googleapis.com/auth/indexing"]


def _service_account_creds(scopes: list[str]):
    """Returns a service-account Credentials object or None if env var missing."""
    blob = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not blob:
        # Fall back to file at automation/gsc-credentials.json if present.
        from pathlib import Path
        here = Path(__file__).resolve().parent / "gsc-credentials.json"
        if here.exists():
            blob = here.read_text(encoding="utf-8")
    if not blob:
        return None
    try:
        from google.oauth2 import service_account
    except ImportError:
        print("Install: pip install google-api-python-client google-auth", file=sys.stderr)
        return None
    return service_account.Credentials.from_service_account_info(
        json.loads(blob), scopes=scopes,
    )


def gsc_client(read_only: bool = True):
    creds = _service_account_creds(GSC_SCOPES_READ if read_only else GSC_SCOPES_RW)
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def indexing_client():
    creds = _service_account_creds(INDEXING_SCOPES)
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    return build("indexing", "v3", credentials=creds, cache_discovery=False)


def gsc_search_analytics(site: str, start: date, end: date,
                         dimensions: list[str], row_limit: int = 5000) -> list[dict]:
    svc = gsc_client(read_only=True)
    if svc is None:
        return []
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "dataState": "all",
    }
    rows = svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])
    return rows


def gsc_submit_sitemap(site: str, sitemap_url: str) -> dict:
    svc = gsc_client(read_only=False)
    if svc is None:
        return {"error": "no_credentials"}
    svc.sitemaps().submit(siteUrl=site, feedpath=sitemap_url).execute()
    return {"ok": True, "submitted": sitemap_url}


def gsc_inspect_url(site: str, url: str) -> dict:
    svc = gsc_client(read_only=True)
    if svc is None:
        return {"error": "no_credentials"}
    body = {"inspectionUrl": url, "siteUrl": site, "languageCode": "en-US"}
    return svc.urlInspection().index().inspect(body=body).execute()


def indexing_publish(url: str, action: str = "URL_UPDATED") -> dict:
    svc = indexing_client()
    if svc is None:
        return {"error": "no_credentials"}
    body = {"url": url, "type": action}
    return svc.urlNotifications().publish(body=body).execute()


# -----------------------------------------------------------------------------
# Google Trends — best-effort public endpoint
# -----------------------------------------------------------------------------

TRENDS_DAILY_URL = (
    "https://trends.google.com/trends/api/dailytrends?hl=en-US&tz=240&geo=US"
)


def trends_rising_topics() -> list[str]:
    """Returns rising search topics across the US for today. Best-effort; returns
    [] if Google's response shape changes or the endpoint is rate-limited."""
    try:
        req = urllib.request.Request(
            TRENDS_DAILY_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode("utf-8", errors="ignore")
        # The endpoint prepends ")]}',\n" as XSS prevention. Strip it.
        text = text.lstrip(")]}'\n").strip()
        payload = json.loads(text)
        topics = []
        for day in (payload.get("default", {}).get("trendingSearchesDays", []) or []):
            for ts in day.get("trendingSearches", []) or []:
                title = (ts.get("title") or {}).get("query")
                if title:
                    topics.append(title)
        return topics
    except Exception as e:  # noqa: BLE001
        print(f"trends_rising_topics failed: {e}", file=sys.stderr)
        return []


# -----------------------------------------------------------------------------
# Google Autocomplete — public suggest endpoint
# -----------------------------------------------------------------------------

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search?client=firefox&q={q}"


def autocomplete(seed: str) -> list[str]:
    try:
        req = urllib.request.Request(
            AUTOCOMPLETE_URL.format(q=urllib.parse.quote_plus(seed)),
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
        return list(payload[1]) if len(payload) > 1 else []
    except Exception:  # noqa: BLE001
        return []


# -----------------------------------------------------------------------------
# Google Ads Keyword Planner — stub
# -----------------------------------------------------------------------------

def keyword_planner_volumes(keywords: list[str]) -> dict[str, dict]:
    """Returns {keyword: {avg_monthly_searches, competition_index}}.

    Stubbed: requires google-ads SDK + developer token + OAuth refresh-token
    + login customer id. Populate the env vars listed in this file's docstring
    and replace this body with a GoogleAdsClient.search() call against
    KeywordPlanIdeaService.

    Without credentials, returns an empty dict so callers can fall back to
    heuristics (see keyword-engine.py).
    """
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not dev_token:
        return {}
    try:
        # Lazy import so this module loads without the dep installed.
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except ImportError:
        print(
            "google-ads SDK not installed. Run: pip install google-ads",
            file=sys.stderr,
        )
        return {}
    # Full implementation requires more than fits in a stub. The shape:
    #   client = GoogleAdsClient.load_from_env()
    #   ki_service = client.get_service("KeywordPlanIdeaService")
    #   request = client.get_type("GenerateKeywordIdeasRequest")
    #   request.customer_id = os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]
    #   request.keyword_seed.keywords.extend(keywords)
    #   request.language = "languageConstants/1000"     # English
    #   request.geo_target_constants.append("geoTargetConstants/2840")  # US
    #   response = ki_service.generate_keyword_ideas(request=request)
    #   return {row.text: {"avg_monthly_searches": row.keyword_idea_metrics.avg_monthly_searches,
    #                       "competition_index": row.keyword_idea_metrics.competition_index}
    #           for row in response}
    print("keyword_planner_volumes: dev_token present, full impl gated on full OAuth setup.")
    return {}


# -----------------------------------------------------------------------------
# Helper: convenience date ranges
# -----------------------------------------------------------------------------

def last_n_days(n: int) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=n)
    return start, end
