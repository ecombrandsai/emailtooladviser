#!/usr/bin/env python3
"""
image-pipeline.py
=================

Runs through automation/image-queue.json. For every page entry, generates
any missing photos via OpenAI gpt-image-1 and any missing graphics via
inline HTML/CSS snippets, then injects them into the corresponding
article HTML at the requested placement.

ENV:
    OPENAI_API_KEY  (required for photo generation)

Install:
    pip install openai requests pillow
"""

import openai
import requests
import os
import json
from PIL import Image
from io import BytesIO
from datetime import datetime
import base64

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def generate_photo(prompt, filename):
    print(f'Generating photo: {filename}')
    if client is None:
        print(f'  OPENAI_API_KEY not set; skipping {filename}')
        return None
    try:
        response = client.images.generate(
            model='gpt-image-1',
            prompt=prompt,
            size='1792x1024',
            quality='standard',
            n=1,
        )
        image_data = response.data[0]
        if hasattr(image_data, 'url') and image_data.url:
            img_response = requests.get(image_data.url)
            img_bytes = img_response.content
        elif hasattr(image_data, 'b64_json') and image_data.b64_json:
            img_bytes = base64.b64decode(image_data.b64_json)
        else:
            print(f'No image data for {filename}')
            return None
        os.makedirs('images', exist_ok=True)
        img = Image.open(BytesIO(img_bytes))
        img = img.convert('RGB')
        img.save(f'images/{filename}', 'JPEG', quality=82, optimize=True)
        print(f'Saved: images/{filename}')
        return f'images/{filename}'
    except Exception as e:
        print(f'Photo error {filename}: {e}')
        return None


def generate_comparison_table(data, title):
    winner = data.get('winner', '')
    columns = data.get('columns', [])
    rows = data.get('rows', [])
    html = f'<div style="margin:2.5rem 0;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);border:1px solid #e2e8f0;"><div style="background:#1a2332;padding:1rem 1.5rem;"><h3 style="color:white;margin:0;font-size:1.1rem;">{title}</h3></div><div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.9rem;"><thead><tr style="background:#f8fafc;">'
    for col in columns:
        html += f'<th style="padding:0.75rem 1rem;text-align:left;font-weight:700;color:#1a2332;border-bottom:2px solid #e2e8f0;">{col}</th>'
    html += '</tr></thead><tbody>'
    for row in rows:
        is_winner = winner and str(row[0]) == winner
        bg = 'background:#f0fdf4;' if is_winner else ''
        html += f'<tr style="{bg}">'
        for i, cell in enumerate(row):
            color = 'color:#10b981;font-weight:700;' if str(cell).startswith('✓') else 'color:#ef4444;' if str(cell).startswith('✗') else 'color:#1a2332;'
            badge = ' <span style="background:#10b981;color:white;font-size:10px;padding:2px 8px;border-radius:20px;font-weight:700;">TOP PICK</span>' if i == 0 and is_winner else ''
            html += f'<td style="padding:0.75rem 1rem;border-bottom:1px solid #f1f5f9;{color}">{cell}{badge}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def generate_stat_callout(stats):
    html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;margin:2.5rem 0;">'
    for stat in stats:
        html += f'<div style="background:linear-gradient(135deg,#eff6ff,#dbeafe);border:2px solid #2563eb;border-radius:12px;padding:1.5rem;text-align:center;"><div style="font-size:2rem;font-weight:900;color:#2563eb;margin-bottom:0.5rem;">{stat["number"]}</div><div style="font-size:0.85rem;color:#475569;line-height:1.4;">{stat["label"]}</div></div>'
    html += '</div>'
    return html


def generate_process_steps(steps, title):
    html = f'<div style="margin:2.5rem 0;"><h3 style="font-size:1.2rem;font-weight:700;color:#1a2332;margin-bottom:1.5rem;">{title}</h3><div style="display:flex;flex-direction:column;gap:1rem;">'
    for step in steps:
        html += f'<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.25rem;background:#f8fafc;border-radius:12px;border-left:4px solid #2563eb;"><div style="width:36px;height:36px;background:#2563eb;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:14px;color:white;flex-shrink:0;">{step["number"]}</div><div><div style="font-weight:700;color:#1a2332;margin-bottom:0.25rem;">{step["title"]}</div><div style="font-size:0.9rem;color:#64748b;line-height:1.5;">{step["description"]}</div></div></div>'
    html += '</div></div>'
    return html


def generate_scorecard(scores, title):
    html = f'<div style="margin:2.5rem 0;background:#f8fafc;border-radius:12px;padding:1.5rem;border:1px solid #e2e8f0;"><h3 style="font-size:1.1rem;font-weight:700;color:#1a2332;margin:0 0 1.25rem 0;">{title}</h3>'
    for score in scores:
        pct = (score['score'] / score['max']) * 100
        color = '#10b981' if pct >= 90 else '#2563eb' if pct >= 75 else '#f59e0b' if pct >= 60 else '#ef4444'
        is_overall = 'Overall' in score['category']
        bg = 'background:#f0fdf4;padding:0.75rem;border-radius:8px;margin-top:0.5rem;' if is_overall else ''
        weight = 'font-weight:700;' if is_overall else ''
        html += f'<div style="margin-bottom:0.75rem;{bg}"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.35rem;"><span style="font-size:0.9rem;color:#1a2332;{weight}">{score["category"]}</span><span style="font-size:0.9rem;font-weight:700;color:{color};">{score["score"]}/{score["max"]}</span></div><div style="background:#e2e8f0;border-radius:999px;height:8px;overflow:hidden;"><div style="background:{color};height:100%;width:{pct}%;border-radius:999px;"></div></div></div>'
    html += '</div>'
    return html


def generate_pricing_table(plans, title):
    html = f'<div style="margin:2.5rem 0;"><h3 style="font-size:1.1rem;font-weight:700;color:#1a2332;margin-bottom:1.25rem;">{title}</h3><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;">'
    for i, plan in enumerate(plans):
        is_rec = i == 0
        border = 'border:2px solid #2563eb;' if is_rec else 'border:1px solid #e2e8f0;'
        badge = '<div style="background:#2563eb;color:white;font-size:10px;font-weight:700;padding:4px 12px;border-radius:20px;text-align:center;margin-bottom:1rem;">RECOMMENDED</div>' if is_rec else ''
        html += f'<div style="background:white;border-radius:12px;padding:1.5rem;{border}">{badge}<div style="font-weight:700;font-size:1.1rem;color:#1a2332;margin-bottom:0.25rem;">{plan["name"]}</div><div style="font-size:1.8rem;font-weight:900;color:#2563eb;margin-bottom:0.25rem;">{plan["price"]}</div><div style="font-size:0.8rem;color:#64748b;margin-bottom:1rem;">{plan["contacts"]}</div><ul style="list-style:none;padding:0;margin:0;">'
        for feature in plan['features']:
            html += f'<li style="padding:0.35rem 0;font-size:0.85rem;color:#475569;display:flex;align-items:center;gap:0.5rem;"><span style="color:#10b981;font-weight:700;">✓</span>{feature}</li>'
        html += '</ul></div>'
    html += '</div></div>'
    return html


def generate_pros_cons(pros, cons, title):
    html = f'<div style="margin:2.5rem 0;"><h3 style="font-size:1.1rem;font-weight:700;color:#1a2332;margin-bottom:1.25rem;">{title}</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;"><div style="background:#f0fdf4;border:1px solid #86efac;border-radius:12px;padding:1.25rem;"><div style="font-weight:700;color:#15803d;margin-bottom:0.75rem;">✓ Pros</div>'
    for pro in pros:
        html += f'<div style="padding:0.35rem 0;font-size:0.9rem;color:#166534;display:flex;align-items:flex-start;gap:0.5rem;"><span style="flex-shrink:0;color:#10b981;">✓</span>{pro}</div>'
    html += '</div><div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:12px;padding:1.25rem;"><div style="font-weight:700;color:#dc2626;margin-bottom:0.75rem;">✗ Cons</div>'
    for con in cons:
        html += f'<div style="padding:0.35rem 0;font-size:0.9rem;color:#991b1b;display:flex;align-items:flex-start;gap:0.5rem;"><span style="flex-shrink:0;">✗</span>{con}</div>'
    html += '</div></div></div>'
    return html


def generate_winner_card(winner, reason, cta_text=None, cta_link=None):
    html = f'<div style="margin:2.5rem 0;background:linear-gradient(135deg,#eff6ff,#dbeafe);border:2px solid #2563eb;border-radius:16px;padding:2rem;"><div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;"><div style="width:32px;height:32px;background:#2563eb;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;color:white;flex-shrink:0;">★</div><div style="font-weight:800;font-size:1.2rem;color:#1a2332;">{winner}</div></div><p style="color:#475569;line-height:1.6;margin:0 0 1.5rem 0;">{reason}</p>'
    if cta_text and cta_link:
        html += f'<a href="{cta_link}" style="display:inline-flex;align-items:center;gap:0.5rem;background:#2563eb;color:white;padding:12px 24px;border-radius:8px;font-weight:700;font-size:0.95rem;text-decoration:none;">{cta_text} →</a>'
    html += '</div>'
    return html


def generate_bar_chart(data, title):
    max_val = max(item['value'] for item in data)
    html = f'<div style="margin:2.5rem 0;background:#f8fafc;border-radius:12px;padding:1.5rem;border:1px solid #e2e8f0;"><h3 style="font-size:1rem;font-weight:700;color:#1a2332;margin:0 0 1.25rem 0;">{title}</h3>'
    for item in data:
        pct = (item['value'] / max_val) * 100
        html += f'<div style="margin-bottom:0.75rem;"><div style="display:flex;justify-content:space-between;margin-bottom:0.35rem;"><span style="font-size:0.85rem;color:#1a2332;font-weight:600;">{item["label"]}</span><span style="font-size:0.85rem;font-weight:700;color:{item["color"]};">{item["value"]}%</span></div><div style="background:#e2e8f0;border-radius:999px;height:10px;overflow:hidden;"><div style="background:{item["color"]};height:100%;width:{pct}%;border-radius:999px;"></div></div></div>'
    html += '</div>'
    return html


def find_insertion_point(content, placement):
    if placement == 'top_of_article':
        for tag in ['<article', '<main', '<body']:
            idx = content.find(tag)
            if idx != -1:
                close = content.find('>', idx)
                return close + 1 if close != -1 else idx
        return -1
    if placement == 'after_intro_section':
        idx = content.find('<h2')
        return idx if idx != -1 else -1
    if placement == 'before_h2_2':
        first = content.find('<h2')
        if first != -1:
            second = content.find('<h2', first + 4)
            return second if second != -1 else -1
        return -1
    if placement == 'before_h2_3':
        first = content.find('<h2')
        if first != -1:
            second = content.find('<h2', first + 4)
            if second != -1:
                third = content.find('<h2', second + 4)
                return third if third != -1 else -1
        return -1
    if placement == 'before_main_cta':
        for marker in ['join.constantcontact.com', 'featured-pick-cta', 'cta-box']:
            idx = content.find(marker)
            if idx != -1:
                start = content.rfind('<div', 0, idx)
                return start if start != -1 else idx
        return -1
    if placement == 'before_verdict_section':
        for marker in ['verdict', 'bottom line', 'our pick', 'winner']:
            idx = content.lower().find(marker)
            if idx != -1:
                start = content.rfind('<h', 0, idx)
                return start if start != -1 else idx
        return -1
    if placement == 'before_alternative_section':
        for marker in ['alternative', 'consider', 'instead', 'better option']:
            idx = content.lower().find(marker)
            if idx != -1:
                start = content.rfind('<h', 0, idx)
                return start if start != -1 else idx
        return -1
    if placement == 'before_pros_cons_section':
        for marker in ['pros and cons', 'advantages', 'strengths']:
            idx = content.lower().find(marker)
            if idx != -1:
                start = content.rfind('<h', 0, idx)
                return start if start != -1 else idx
        return -1
    if placement == 'before_comparison_section':
        for marker in ['compare', 'comparison', 'how they stack']:
            idx = content.lower().find(marker)
            if idx != -1:
                start = content.rfind('<h', 0, idx)
                return start if start != -1 else idx
        h2 = content.find('<h2')
        if h2 != -1:
            second = content.find('<h2', h2 + 4)
            return second if second != -1 else h2
        return -1
    end = content.rfind('</article>')
    if end != -1:
        return end
    end = content.rfind('</main>')
    return end if end != -1 else len(content) - 10


def insert_into_html(content, html_to_insert, placement):
    idx = find_insertion_point(content, placement)
    if idx == -1:
        end = content.rfind('</article>')
        idx = end if end != -1 else content.rfind('</main>')
        if idx == -1:
            return content
    return content[:idx] + '\n' + html_to_insert + '\n' + content[idx:]


def generate_graphic(asset):
    gtype = asset.get('graphic_type')
    title = asset.get('title', '')
    if gtype == 'comparison_table':
        return generate_comparison_table(asset.get('data', {}), title)
    elif gtype == 'stat_callout':
        return generate_stat_callout(asset.get('stats', []))
    elif gtype == 'process_steps':
        return generate_process_steps(asset.get('steps', []), title)
    elif gtype == 'scorecard':
        return generate_scorecard(asset.get('scores', []), title)
    elif gtype == 'pricing_table':
        return generate_pricing_table(asset.get('plans', []), title)
    elif gtype == 'pros_cons':
        return generate_pros_cons(asset.get('pros', []), asset.get('cons', []), title)
    elif gtype == 'winner_card':
        return generate_winner_card(asset.get('winner', ''), asset.get('reason', ''), asset.get('cta_text'), asset.get('cta_link'))
    elif gtype == 'bar_chart':
        return generate_bar_chart(asset.get('data', []), title)
    return ''


def process_page(page):
    url = page['url']
    if not os.path.exists(url):
        print(f'File not found: {url}')
        return
    with open(url, 'r', encoding='utf-8') as f:
        content = f.read()
    changed = False
    for asset in page.get('assets', []):
        if asset.get('status') == 'completed':
            continue
        placement = asset.get('placement', 'top_of_article')
        html_to_insert = ''
        if asset['type'] == 'photo':
            filename = asset['filename']
            img_path = f'images/{filename}'
            if not os.path.exists(img_path):
                result = generate_photo(asset['prompt'], filename)
                if not result:
                    continue
            keyword = asset.get('keyword', '')
            check = f'src="/{img_path}"'
            if check not in content:
                html_to_insert = f'<figure class="hero-image" style="margin:0 0 2.5rem 0;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);"><img src="/{img_path}" alt="{keyword} - EmailToolAdviser" width="100%" height="auto" loading="lazy" style="display:block;width:100%;height:auto;max-height:480px;object-fit:cover;"></figure>'
        elif asset['type'] == 'graphic':
            asset_id = asset.get('id', '')
            check_marker = f'data-graphic="{asset_id}"'
            if check_marker not in content:
                graphic_html = generate_graphic(asset)
                if graphic_html:
                    html_to_insert = f'<div data-graphic="{asset_id}">{graphic_html}</div>'
        if html_to_insert:
            content = insert_into_html(content, html_to_insert, placement)
            asset['status'] = 'completed'
            asset['completed_date'] = datetime.now().isoformat()
            changed = True
    if changed:
        with open(url, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated: {url}')


def run_pipeline():
    with open('automation/image-queue.json', 'r') as f:
        queue = json.load(f)
    for page in queue['pages']:
        process_page(page)
    with open('automation/image-queue.json', 'w') as f:
        json.dump(queue, f, indent=2)
    print('Image pipeline complete')


if __name__ == '__main__':
    run_pipeline()
