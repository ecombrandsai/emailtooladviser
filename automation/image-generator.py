#!/usr/bin/env python3
"""
image-generator.py
==================

Generates editorial header images for articles. Reads recently published
URLs from publish-log.json, asks Claude (claude-sonnet-4-6) for an editorial
image prompt tuned to the article's topic, then calls Higgsfield's image
generation endpoint and saves the result alongside the article.

Usage:
    python3 image-generator.py --limit 3
    python3 image-generator.py --keyword-id 42
    python3 image-generator.py --dry-run

Env:
    ANTHROPIC_API_KEY     — for the prompt-writing step
    HIGGSFIELD_API_KEY    — for the image generation step
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

THIS_DIR = Path(__file__).resolve().parent
SITE_ROOT = THIS_DIR.parent
CONFIG_PATH = THIS_DIR / "config.json"
QUEUE_PATH = THIS_DIR / "keyword-queue.json"
PUBLISH_LOG_PATH = THIS_DIR / "publish-log.json"
IMAGES_DIR = SITE_ROOT / "images"

HIGGSFIELD_ENDPOINT = "https://api.higgsfield.ai/v1/images/generations"
HIGGSFIELD_MODEL = "nano_banana_2"


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug_from_url(url: str) -> str:
    path = urlparse(url).path
    if path.endswith("/"):
        return "home"
    return Path(path).stem


def claude_prompt_for(keyword: str, item_type: str, cfg: dict) -> str:
    try:
        import anthropic  # type: ignore
    except ImportError:
        sys.exit("pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set.")

    client = anthropic.Anthropic(api_key=api_key)
    system = textwrap.dedent(f"""
        You are a creative director for {cfg['site_name']}, an editorial site
        about email marketing for small businesses.

        Write a single concise image-generation prompt (under 200 words) for
        an editorial header image. The image should be:

        - Photographic, modern, magazine-quality, NOT illustrated.
        - Tied to small-business email marketing (laptop on a desk, a small
          shop owner at their counter, a phone showing an inbox, a printed
          newsletter — whatever matches the article's topic).
        - 16:9 aspect ratio, well-lit, professional, NO text, NO logos, NO
          watermarks, NO numbers.
        - Tonally credible — the kind of image you'd see at the top of a Wired,
          NYT Strategy, or Smithsonian article.

        Output: ONLY the prompt text, nothing else.
    """).strip()

    user = textwrap.dedent(f"""
        Write the image prompt. Article details:
        - Type: {item_type}
        - Keyword target: {keyword!r}
    """).strip()

    resp = client.messages.create(
        model=cfg["claude_model"],
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def higgsfield_generate(prompt: str, dest: Path) -> None:
    import urllib.request
    api_key = os.environ.get("HIGGSFIELD_API_KEY")
    if not api_key:
        sys.exit("HIGGSFIELD_API_KEY not set.")

    body = json.dumps({
        "model": HIGGSFIELD_MODEL,
        "prompt": prompt,
        "aspect_ratio": "16:9",
        "quality": "high",
        "n": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        HIGGSFIELD_ENDPOINT, data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read())

    images = payload.get("data") or payload.get("images") or []
    if not images:
        sys.exit(f"Higgsfield returned no images. Response: {payload}")
    first = images[0]
    url = first.get("url") or first.get("output_url")
    if not url:
        sys.exit(f"No image URL in response: {first}")
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())


def lookup_keyword(queue: dict, url: str) -> dict | None:
    """Match a publish-log url to a keyword in the queue (by URL or slug)."""
    keywords = queue.get("keywords", [])
    slug = slug_from_url(url)
    for kw in keywords:
        if kw.get("url") == url:
            return kw
        # Fallback: match slugified keyword
        from_kw = kw["keyword"].lower().replace(" ", "-")
        if from_kw == slug or slug.startswith(from_kw[:30]):
            return kw
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate header images for articles.")
    parser.add_argument("--limit", type=int, default=3,
                        help="Max images to generate this run.")
    parser.add_argument("--keyword-id", type=int, default=None,
                        help="Generate for a specific keyword id.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts, don't call Higgsfield.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing images.")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)
    queue = load_json(QUEUE_PATH)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    if args.keyword_id is not None:
        candidates = [k for k in queue["keywords"] if k["id"] == args.keyword_id]
    else:
        log = load_json(PUBLISH_LOG_PATH) if PUBLISH_LOG_PATH.exists() else {"entries": []}
        candidates = []
        for entry in sorted(log["entries"], key=lambda e: e.get("published_at", ""),
                            reverse=True):
            url = entry.get("url", "")
            if not url:
                continue
            kw = lookup_keyword(queue, url)
            if kw:
                kw = {**kw, "_url": url}
                candidates.append(kw)
            if len(candidates) >= args.limit:
                break

    if not candidates:
        print("Nothing to do.")
        return

    for kw in candidates:
        slug = slug_from_url(kw.get("_url") or kw["keyword"].replace(" ", "-"))
        out_path = IMAGES_DIR / f"{slug}.jpg"
        if out_path.exists() and not args.force:
            print(f"Exists, skipping: {out_path}")
            continue

        print(f"→ {kw['keyword']}")
        prompt = claude_prompt_for(kw["keyword"], kw["type"], cfg)
        print(f"  prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
        if args.dry_run:
            continue
        higgsfield_generate(prompt, out_path)
        print(f"  ✓ Saved {out_path}")
        time.sleep(2)

    print("Done.")


if __name__ == "__main__":
    main()
