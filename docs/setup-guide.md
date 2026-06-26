# EmailToolAdviser Network — Setup Guide

This guide takes the network from "five repos in GitHub" to "five live sites publishing content daily and tracking rankings automatically." Plan on 60-90 minutes for the full setup, most of it waiting on DNS and a few API key signups.

The architecture, at a glance:

```
emailtooladviser.com               <-- core domain, only one that links to the affiliate URL
├── bestemailtoolreviews.com       --> sends traffic to emailtooladviser.com
├── emailmarketingrated.com        --> sends traffic to emailtooladviser.com
├── emailtoolratings.com           --> sends traffic to emailtooladviser.com
└── smallbizemailhub.com           --> sends traffic to emailtooladviser.com
```

Every site is a static HTML repo. Cloudflare Pages builds and serves on push. A daily GitHub Action calls Anthropic Claude to generate articles and commits them back to main. Another action submits the new URLs to Google Search Console. The dashboard at `/dashboard/` reads the JSON files in `/data/` to show the state of the network.

---

## Section 1 — Connecting domains to Cloudflare Pages

You'll do this once per domain. The 5 domains all follow the same playbook.

### 1.1 Create a Cloudflare Pages project

1. Log in to Cloudflare → **Workers & Pages** → **Create application** → **Pages**.
2. Choose **Connect to Git**. Authorize Cloudflare to read your `ecombrandsai` GitHub account.
3. Select the repo for the domain you're setting up (e.g. `emailtooladviser`).
4. Set the project name to match the repo (e.g. `emailtooladviser`). The deploy.yml workflow already references this name.
5. Build settings:
   - Framework preset: **None**
   - Build command: *(leave empty)*
   - Build output directory: `/`
   - Root directory: *(leave empty)*
6. Click **Save and Deploy**. The first deploy publishes the site to `<project>.pages.dev`.

### 1.2 Connect your custom domain

1. Inside the project, go to **Custom domains** → **Set up a custom domain**.
2. Enter the production domain (e.g. `emailtooladviser.com`).
3. If you've already added the domain to Cloudflare DNS, Pages auto-creates the CNAME. If not, follow the prompts to either:
   - Transfer the domain to Cloudflare DNS (recommended), or
   - Add the CNAME record at your existing registrar:
     ```
     CNAME  @     <project>.pages.dev.
     CNAME  www   <project>.pages.dev.
     ```
4. Wait 5-15 minutes for DNS propagation. The custom domain shows **Active** in the dashboard once it's live.

### 1.3 Verify the deploy works

Hit the production URL in a browser. You should see the homepage. If you get a 404 or stale content, force-redeploy from the Cloudflare Pages dashboard.

Repeat 1.1-1.3 for all 5 domains.

---

## Section 2 — GitHub Secrets you'll need

Set these on each repo at **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | What it does | Where to get it |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | Lets GitHub Actions deploy to your Cloudflare Pages project | Cloudflare → My Profile → API Tokens → Create Token → use the **Edit Cloudflare Workers** template (sufficient for Pages) |
| `CLOUDFLARE_ACCOUNT_ID` | Identifies your Cloudflare account | Cloudflare dashboard → right sidebar on any page |
| `ANTHROPIC_API_KEY` | Used by `content-generator.py` to call Claude (claude-sonnet-4-6) | console.anthropic.com → API keys |
| `HIGGSFIELD_API_KEY` | Optional. Used by `image-generator.py` for header images | higgsfield.ai → API keys (or the integrated MCP if you stay inside Higgsfield) |
| `GSC_SERVICE_ACCOUNT_JSON` | Optional. JSON for a service account that has GSC read+submit access | See Section 3 |

You can add the same set of secrets to all 5 repos (each repo only uses the ones relevant to it — the satellites don't need `ANTHROPIC_API_KEY` until you turn on their content pipelines).

---

## Section 3 — Google Search Console setup

This unlocks `rank-tracker.py`, `search-console.py`, and the weekly report. Skip it for now if you want — the site works without it.

### 3.1 Add each domain as a GSC property

1. Go to [search.google.com/search-console](https://search.google.com/search-console).
2. Click **Add property** → **Domain property** → enter the bare domain (`emailtooladviser.com`).
3. Verify ownership via DNS TXT record. If your DNS lives in Cloudflare, paste the TXT record into a new DNS entry, save, and click **Verify** in GSC. Most properties verify in under a minute.
4. Repeat for all 5 domains.

### 3.2 Create a service account

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → **IAM & Admin → Service Accounts** → **Create service account**.
2. Name it `emailtooladviser-rank-tracker`. Skip the optional roles step.
3. Open the new service account → **Keys** → **Add key → Create new key → JSON**. Download the JSON file.
4. Copy the `client_email` from the JSON (looks like `something@project.iam.gserviceaccount.com`).
5. Back in Google Search Console, open each property → **Settings → Users and permissions → Add user**. Paste in the service account email and grant **Owner** access.

### 3.3 Save credentials locally

Save the downloaded JSON as `automation/gsc-credentials.json` in each repo (gitignored by default — don't commit it!).

For CI, paste the full JSON as the `GSC_SERVICE_ACCOUNT_JSON` GitHub secret. The deploy and content-pipeline workflows write it to disk on each run.

### 3.4 Enable the Search Console API and Indexing API

In the [Google Cloud Console API Library](https://console.cloud.google.com/apis/library), enable:
- **Google Search Console API**
- **Web Search Indexing API** (only needed if you want `search-console.py --action submit-urls` to work)

---

## Section 4 — Running the content pipeline

### 4.1 Run content-generator.py locally

```bash
cd emailtooladviser/
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
python3 automation/content-generator.py --count 1
```

The script will:
1. Read the next unpublished keyword from `automation/keyword-queue.json` (priority 1 first).
2. Call Claude with a system prompt that locks in the brand voice, schema, and CTA structure.
3. Save the resulting HTML to the correct folder.
4. Mark the keyword as published in the queue.
5. Append to `automation/publish-log.json`.
6. Add the URL to `sitemap.xml`.

For a dry run (no API call, no write):
```bash
python3 automation/content-generator.py --dry-run --count 1
```

### 4.2 Automate daily publishing

The `.github/workflows/content-pipeline.yml` runs at 06:00 UTC daily and generates 3 articles by default. You can manually trigger it from the **Actions** tab in GitHub with a custom count.

### 4.3 Monitor the publish log

`automation/publish-log.json` records every published URL with timestamp, domain, type, and originating keyword id. The dashboard reads this for the "published this week" metric.

### 4.4 Add new keywords

Edit `automation/keyword-queue.json` and append entries with `status: "unpublished"`. Priorities 1-5; 1 publishes first. The queue is pre-seeded with 100 keywords ranked by intent and difficulty.

---

## Section 5 — Using the dashboard

### 5.1 Access the dashboard

The dashboard lives at `/dashboard/index.html` and renders any time the site is reachable. For local dev, just open the file in a browser. In production, hit:

```
https://emailtooladviser.com/dashboard/
```

It's `Disallow: /dashboard/` in robots.txt so search engines won't index it.

If you want auth on this URL, add a Cloudflare Access policy to the route — that's the safest path; static auth in HTML is trivially bypassable.

### 5.2 Interpret the metrics

- **Revenue cards** read `/data/revenue.json`. This file is updated by your CPA tracking pipeline (manually for now; later you can wire it to a webhook from Constant Contact's affiliate report).
- **Traffic cards** read `/data/traffic.json`. Populate it from your analytics tool of choice (Cloudflare Web Analytics or GA4).
- **Content cards** read `/data/content.json` and `/automation/keyword-queue.json`. These update automatically as the content pipeline runs.
- **Rankings cards** read `/data/rankings.json`. Populated by `rank-tracker.py` (Section 3).
- **Domain breakdown table** rolls up per-domain stats from the same JSON files.
- **Top moving keywords** comes from `rankings.json → movers_up`.
- **Needs attention** auto-builds from movers_down, low content queue, and other signals.

### 5.3 Quick actions

The buttons in the dashboard don't have backend hooks by default. Wire them to your CI runner of choice (GitHub Actions `workflow_dispatch`, a webhook URL, or a small Cloudflare Worker) if you want one-click triggers. For now, they show the script each button corresponds to — useful as documentation.

### 5.4 Weekly report

`rank-tracker.py --email-report` sends the HTML report at `/reports/weekly-report.html` via SMTP. Configure SMTP credentials in `automation/config.json` under the `smtp` key.

---

## Section 6 — Spinning up the 4 satellites

The `satellite-template/` directory has everything needed; `satellite-template/setup.py` does the rendering and GitHub push for you.

### 6.1 One-liner per satellite

```bash
cd emailtooladviser-network/
python3 satellite-template/setup.py \
  --domain bestemailtoolreviews.com \
  --title "Best Email Tool Reviews" \
  --niche "email marketing reviews and rankings" \
  --description "Independent reviews and rankings of the best email marketing tools for small businesses." \
  --out-dir . \
  --github-token "$GITHUB_TOKEN" \
  --github-user ecombrandsai
```

That command will:
1. Copy `satellite-template/` to `./bestemailtoolreviews-com/`.
2. Replace all `{{...}}` tokens throughout the new directory.
3. `git init`, `git add`, and create the initial commit.
4. Call the GitHub API to create `ecombrandsai/bestemailtoolreviews-com`.
5. `git push -u origin main`.

Repeat for each satellite, varying the `--domain`, `--title`, `--niche`, and `--description`:

```bash
# emailmarketingrated.com
python3 satellite-template/setup.py \
  --domain emailmarketingrated.com \
  --title "Email Marketing Rated" \
  --niche "email platform ratings and benchmarks" \
  --description "Independent ratings and benchmark data for the top email marketing platforms." \
  --out-dir . --github-token "$GITHUB_TOKEN" --github-user ecombrandsai

# emailtoolratings.com
python3 satellite-template/setup.py \
  --domain emailtoolratings.com \
  --title "Email Tool Ratings" \
  --niche "email marketing tool ratings and scoring" \
  --description "Star ratings, scoring, and editorial summaries for the leading email marketing tools." \
  --out-dir . --github-token "$GITHUB_TOKEN" --github-user ecombrandsai

# smallbizemailhub.com
python3 satellite-template/setup.py \
  --domain smallbizemailhub.com \
  --title "Small Biz Email Hub" \
  --niche "email marketing for small businesses and local services" \
  --description "Email marketing playbooks and tool picks for restaurants, salons, contractors, and other local small businesses." \
  --out-dir . --github-token "$GITHUB_TOKEN" --github-user ecombrandsai
```

### 6.2 Wire each satellite to Cloudflare Pages

For each satellite repo, repeat Section 1. Use the satellite's domain when prompted. The project name in the `deploy.yml` was already token-replaced by `setup.py`.

### 6.3 Verify cross-domain CTAs

Open each satellite homepage and click "See Our Top Email Marketing Pick" — it should land you on `https://emailtooladviser.com/`. Click the secondary "Get Started with Constant Contact" — it should land you on `https://join.constantcontact.com/join-now`.

---

## Section 7 — Day-to-day operations

Once everything is wired:

- **Daily:** GitHub Action publishes 3 new articles per site at 06:00 UTC. Check the Actions tab for failures.
- **Weekly:** The rank-tracker GitHub Action runs (configurable cron — uncomment in `content-pipeline.yml`). The weekly report lands in `/reports/weekly-report.html` and (optionally) your inbox.
- **Monthly:** Refresh pricing tiers in articles if any tool's prices change. The `keyword-queue.json` priorities can be reshuffled based on which keywords are climbing.

For any single command reminder, the script's `--help` flag prints usage:

```bash
python3 automation/content-generator.py --help
python3 automation/sitemap-generator.py --help
python3 automation/rank-tracker.py --help
python3 automation/search-console.py --help
python3 automation/image-generator.py --help
python3 satellite-template/setup.py --help
```

That's it. The network runs on its own once the secrets are in place.
