# Post-Live Watch

A post-live campaign triage dashboard for Confluencr-style influencer marketing — proof-of-work for the Walnut Folks Group "AI Product Engineer" role. The JD asks for "AI workflows that screen, score or summarise campaign data"; this is a working one.

**All data is SAMPLE DATA.** Two fictional brands (GlowLeaf, LumaDerm), 20 fictional creators, synthetic metrics. There is a real, gated Instagram connector (`app/metrics/`, see [docs/meta-setup.md](docs/meta-setup.md)) — it is tested against recorded response fixtures, not a live account, because no Meta app exists for this project yet.

## The core idea: rules first, AI on top

Every flag in this system comes from a **transparent, deterministic rule** reading a **single editable config file** (`config/thresholds.yaml`). AI never decides whether something is a problem — it only adds language and judgment on top of a rule that already fired (explaining *why* a post underperformed, classifying Hinglish/sarcastic comments, drafting a nudge message). Turn AI off and the app still works end-to-end on keyword matching and template text.

The rules engine is built and `pytest`-verified **before any UI code** — see `tests/test_rules.py`, which checks that all 12 named problems trigger on exactly the right seeded posts. That correctness is the thing actually being evaluated here, not the dashboard's polish.

## The 12 detectors

| # | Problem | Rule | AI enhancement |
|---|---|---|---|
| 1 | Not posted | no post after due date + grace | — |
| 2 | Posted late | actual − scheduled time > threshold | — |
| 3 | Missing disclosure | caption lacks `#ad`/"Paid Partnership" | — |
| 4 | Missing tag/link/hashtag | caption + link-sticker checks | — |
| 5 | Underperforming | reach below promise % and creator avg % | explains likely cause |
| 6 | Suspicious engagement | like:comment ratio or day-over-day spike | — |
| 7 | Negative sentiment spike | keyword list, count/ratio threshold | Hinglish/sarcasm classification |
| 8 | Deleted/archived early | still_live 1→0 before campaign end | — |
| 9 | Caption edited / off-brief claim | caption diff + banned-phrase match | paraphrase detection note |
| 10 | Story expired without proof | Story past 24h, no screenshot | — |
| 11 | Competitor post | competitor mention within N days | — |
| 12 | Viral winner (positive) | reach ≫ creator average | suggests boost/whitelist angle |

All thresholds, severities, and the Act now / Needs a look / OK cutoffs live in `config/thresholds.yaml` — nothing is hardcoded in the detector code (`app/rules/detectors.py`).

## The campaign brief is a default, not a law

A real creator deal negotiates things away from the campaign brief: a waived hashtag, a barter
payment with no cash fee, no reach guarantee at all. `deliverables` carries nullable overrides
(`required_disclosure`, `required_tag`, `required_hashtag`, `requires_link_sticker`, `deal_type`,
`min_reach`, …) that are resolved against the campaign default in one place —
`app/rules/contract.py:resolve_terms` — before any detector runs. No detector in
`detectors.py` knows a negotiation happened; it only ever sees the resolved result via
`PostContext`. When a requirement doesn't apply, the reason shows up as a `contract_notes` entry
on the card (visible in `/queue` and `/creators/<id>`) instead of the rule just going quietly
silent.

This also means a creator's deal can be a package — "1 reel + 2 stories" — not one deliverable.
`app/dashboard.py:_creator_deliverables` evaluates every deliverable a creator has and
`_rollup_campaign_status` reports the worst status across the package plus a delivered counter,
so `/creators` and `/creators/<id>` never silently collapse a multi-part deal down to one
arbitrarily-picked post the way an unordered `.fetchone()` used to.

## Deal intake: AI drafts, a human confirms

**New Deal** (`/intake`) turns an account manager's shorthand note, such as *"Signed Priya for 2 reels + 1 story, barter worth ₹5k, no reach guarantee, skipping our hashtag due to an exclusivity clause, due in 3 days"*, into real `creators`, `deliverables` and not-yet-posted `posts` rows. This is the one AI task whose output becomes an input the rules engine measures against, so it is fenced in:

- **Drafting.** AI (`app/ai/provider.py:parse_deal_brief`) or, with AI off, a deterministic keyword extractor (`app/ai/templates.py:parse_deal_brief_fallback`) only produces a draft.
- **Checking.** `app/intake.py` normalises and validates the draft without trusting it.
- **Preview.** The manager reviews an editable preview that shows the exact contract notes the queue will later display.
- **Confirming.** Nothing is written until the manager approves or edits, using the same Approve / Edit / Dismiss pattern as the Flag Queue. Each created deliverable logs a `source='intake'` row in the Decision Log, holding the raw brief.

Hard limits:

- **Disclosure can never be waived** through intake.
- **The AI is forbidden from inventing a creator's average reach or engagement.** A new creator's averages are estimated from follower count using `config/thresholds.yaml → intake`, labelled "Estimated reach" on their profile, and recorded as `am_entered` only if the manager types a real figure.
- **Existing creators are never edited.** Naming one attaches a deliverable to them. A first-name match ("Priya" → `@glowgirlpriya`) is only ever offered as a suggestion.
- **Not-yet-due deliverables don't count.** A deliverable whose due day hasn't arrived is left out of the overview's live percentage and the creator's reliability score.
- **No score without evidence.** A creator with no history and nothing due yet gets "New — no track record yet", not a score.

## Multiple campaigns, including ones already in flight

`/campaigns` creates, lists, and switches between campaigns — the seeded
GlowLeaf demo is no longer the only one the app can hold. Creating one
(`/campaigns/new`) is the same AI-drafts/human-confirms shape as deal intake,
just at campaign scope: type the campaign basics into a form, paste a brief
for the creator deals (or type them one line per creator), review the draft,
confirm. `app/campaign_intake.py` reuses `app/intake.py`'s per-creator
validation and writer rather than reimplementing it.

An account manager entering a campaign that's already running tells it how
many days it's been live; `app/campaign_intake.py` back-computes `start_date`
from that, so the campaign immediately reports the right day. Every campaign
created this way runs on a **live clock** — its day is derived from
`start_date` against wall-clock time (`app/db.py:get_campaign_day`) — while
the original seeded demo stays on the **simulated** clock the day-simulator
has always driven, so the existing "Advance day" walkthrough still works.
Either clock can be switched from `/campaigns`.

Each creator's deliverables are scoped to the ONE campaign being viewed —
`app/dashboard.py` and `app/reliability.py` never roll a creator's status or
reliability score across campaigns they're independently signed to (a
creator's other active campaigns are listed, not folded in, on their
profile). This used to be a real bug: both modules queried a creator's
deliverables with no campaign filter at all, correct only because exactly
one campaign existed. `tests/test_campaign_scoping.py`, and the seeded
LumaDerm campaign sharing two creators with GlowLeaf, are the standing
regression guard.

`/campaigns/{id}/edit` is the "set format to update a campaign" surface —
name, disclosure, tag, hashtag, link-sticker default, duration, banned
claims. Adding a creator to an existing campaign is the same `/intake` flow
every deal already goes through, now scoped to whichever campaign is
selected.

## Instagram metrics connector (gated, built against fixtures)

A campaign can pull real post metrics instead of relying on an account
manager typing numbers in. `app/metrics/` is a 3-tier provider:

- **`instagram`** — two Meta API tiers, degrading per creator: branded
  content (reach + full insights, needs the post tagged `#ad`/"Paid
  Partnership" with the brand and App Review) falling back to the public
  `business_discovery` endpoint (caption/likes/comments, never reach).
- **`manual`** — an account manager types a post's current numbers into a
  per-deliverable form (`/deliverables/{id}/metrics`); written with the same
  `source='am_entered'` label every other manual figure in this app carries.
- **`seeded`** — the demo data, already written at seed time; nothing to
  fetch.

No Meta app exists for this project yet, so the connector is tested against
recorded response fixtures (`tests/fixtures/meta/`), not a live token — see
[docs/meta-setup.md](docs/meta-setup.md) for the capability table (comment
text and Story insights are not obtainable on *any* tier, from anyone, short
of the creator's cooperation), the setup checklist, and what's assumed vs.
verified. `app/rules/detectors.py`'s rule 5 and rule 12 skip cleanly — never
scoring a missing reach figure as zero — on a post whose only source is the
public tier, and the card explains why via a `data_notes` entry instead of
leaving the gap unexplained.

## Running it locally

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

python scripts/seed.py --reset   # generates data/postlivewatch.db — 2 campaigns, 20 creators
pytest -v                        # all 180 should pass — the correctness proof

cp .env.example .env              # optional: add OPENROUTER_API_KEY to enable AI
uvicorn app.main:app --reload --port 8420
```

The React frontend runs separately and forwards `/api` to that uvicorn server:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Open `http://localhost:5173/` (React app) or `http://localhost:8420/` (the server-rendered Jinja2 + HTMX version of the same screens). Use the **Advance day ▶** control in the top nav to replay the 7-day campaign and watch flags appear over time (exactly what the day-simulator is for). Hit `/api/debug` directly for the full computed state as JSON — the same proof-of-correctness surface the tests check against.

Screens: Campaign Overview (`/`) · Flag Queue (`/queue`) · Creator Profiles (`/creators`) · Brand Daily Report (`/report`, read-only) · Decision Log (`/decisions`) · New Deal (`/intake`) · Campaigns (`/campaigns`, `/campaigns/new`, `/campaigns/{id}/edit`) · manual metrics entry (`/deliverables/{id}/metrics`).

**Campaign management is server-rendered only (`app/templates/`) for now.** The JSON API under `/api/campaigns`, `/api/campaigns/parse`, `/api/campaigns/confirm`, `/api/deliverables/{id}/metrics`, and `/api/creators/research/{handle}` is fully built and tested (`tests/test_api_campaigns.py`, `tests/test_api_metrics_routes.py`) — the React app (`frontend/`) just doesn't have matching pages/routes wired up yet. Use the Jinja2+HTMX surface at `:8420` for campaign creation, switching, and editing until that catches up.

**AI on/off**: the pill button in the nav toggles `app_state.ai_enabled` in the DB. With no `OPENROUTER_API_KEY` set, every AI task function (`app/ai/provider.py`) falls back to its template/keyword counterpart automatically — nothing breaks.

## Frontend

There are two frontends for the same screens. Both read the same data from `app/dashboard.py`, so they can't disagree.

- **`frontend/`**: the deployed one. React + TypeScript (Vite + React Router), styled with the Claude Design stylesheet (`app/static/app.css`, copied as-is). It talks only to the JSON API in `app/api.py`.
- **`app/templates/`**: the original server-rendered Jinja2 + HTMX pages, still served by FastAPI at the API's own URL.

See `docs/designs/frontend-brief.md` for the content and data contract of each screen.

JSON API (all under `/api`). Every `GET` below also accepts an optional
`?campaign_id=` to read a different campaign than the server's current
selection, without changing it:

- `GET`: `state`, `overview`, `queue`, `creators`, `creators/{id}`, `report`, `decisions`, `intake` (campaign defaults), `debug`, `campaigns`, `campaigns/{id}`.
- `POST`: `flags/{post_id}/decide` (JSON body: `action`, `message_text`, `original_message`, `flag_rule_id`), `simulate/advance-day`, `simulate/reset-day`, `settings/ai-toggle`.
- `POST` (deal intake):
  - `intake/parse` takes `{brief_text}` and returns the draft and its blocking errors, without writing anything.
  - `intake/confirm` takes `{action, original_draft, draft}`. Approve commits `original_draft`, edit commits `draft`, and dismiss writes nothing.
- `POST` (campaign management):
  - `campaigns/select` takes `{campaign_id}`.
  - `campaigns/{id}/clock` takes `{mode: "live"|"simulated"}`.
  - `campaigns/{id}/edit` takes the campaign's editable fields and returns the updated row, or `422` with field errors.
  - `campaigns/parse` takes `{campaign: {...}, creators_brief_text}` — same shape split as `/campaigns/new`'s form: typed campaign fields plus a free-text (or one-line-per-creator) creator brief.
  - `campaigns/confirm` takes `{action, original_draft, draft}`, same approve/edit/dismiss pattern as deal intake, at campaign scope.
  - `campaigns/{id}/sync` runs `app/metrics/sync.py` for that campaign against whichever provider its `metrics_provider` names.
  - `deliverables/{id}/metrics` takes `{day_number, reach, likes, comments_count, saves, shares, still_live}` and writes one manually-entered snapshot.
- `GET /creators/research/{handle}` — pre-signing Instagram research (followers, a measured engagement rate, recent captions) via the public tier; `409` if the connector isn't configured, `404` if the account can't be looked up.
- `GET /healthz` returns `{"ok": true}`.

## Deploying ($0: Render + Vercel + GitHub Actions)

```
Browser ──> Vercel (frontend/, static React build)
              └─ rewrite /api/* ──> Render free web service (Dockerfile: FastAPI + SQLite)
GitHub Actions keep-alive ──(every 10 min, IST daytime)──> Render /healthz
```

- **API on Render**, defined in `render.yaml`: Docker runtime, `free` plan, health check on `/healthz`. Render's own auto-deploy is off; CI deploys it (see **CI** below).
  - One-time setup: Render dashboard → **New → Blueprint** → pick this repo → paste `OPENROUTER_API_KEY` (optional; the app runs on template fallbacks without it).
  - The service URL is `https://post-live-watch.onrender.com`.
- **Frontend on Vercel**: project root is `frontend/`, and pushes to `main` auto-deploy. `frontend/vercel.json` rewrites `/api/*` to the Render URL, so the browser only ever sees one origin (no CORS), and sends every other path to `index.html` for client-side routing.
- **Keep-alive**: Render's free plan sleeps a service after 15 idle minutes and wipes its filesystem (including the SQLite DB) when it does. `.github/workflows/keepalive.yml` pings `/healthz` every 10 minutes from 08:30 to 00:30 IST (about 500 h a month). The 750 free instance-hours are shared by every free service in the Render workspace, and exceeding them suspends all of them, so the service is allowed to sleep overnight.
  - A redeploy still re-seeds the demo data back to day 1. That's acceptable because all data is synthetic.
  - GitHub pauses scheduled workflows after 60 days with no repo activity. Re-enable it from the Actions tab.
  - If the ping is ever delayed and Render is waking up, the frontend shows a "Waking up the server…" banner.
- **AI uses free OpenRouter models only.** `OPENROUTER_MODELS` is an ordered list, tried in groups of 3 (OpenRouter's maximum per request).
  - Any id that isn't a `:free` variant (or `openrouter/free`) is dropped in code, and every request carries a `max_price` of 0, so a paid request can't happen.
  - Answers are cached per prompt, and the current day's notes are generated in the background.
  - After an account rate limit (free models allow about 50 requests a day), the app falls back to templates until the limit resets.
- **CI**: `.github/workflows/ci.yml` runs `pytest` and the frontend build on every push and PR.
  - On pushes to `main`, a `deploy-api` job then triggers the Render deploy through Render's API and waits for it to go live.
  - It runs only after both test jobs pass, and is skipped when only `frontend/`, `docs/` or Markdown changed.
  - It needs the repo secret `RENDER_API_KEY` and the repo variable `RENDER_SERVICE_ID`.

### Self-hosted alternative (any VM with Docker)

```bash
cp .env.example .env    # fill in OPENROUTER_API_KEY if you have one
docker compose up -d --build
```

This runs the API and the server-rendered screens with a persistent `./data` volume, so the SQLite DB, decision log, and day-simulator state survive restarts. The seed script only runs if `data/postlivewatch.db` doesn't exist yet. Point a reverse proxy (Caddy, nginx or Cloudflare Tunnel) at port `8420`. To update after a `git pull`, run `docker compose up -d --build` again.

## Optional: n8n daily brand-report trigger

Not built by default (explicitly optional in the brief, and kept out of the critical path — see the design doc's reasoning on why n8n stays out of the rules/scoring pipeline entirely). If you want it: a scheduled n8n workflow hitting `GET /report` (HTML) or `GET /api/report` (JSON) and delivering the result via email/Slack/webhook.

## Out of scope

Authentication, multi-tenant support, payments, auto-sending messages, a
mobile app, a scheduled/nightly sync job (`/campaigns/{id}/sync` is
manually triggered, not cron-driven) — per the brief, or not yet built.
The React frontend doesn't have campaign-management pages yet (see
**Frontend** above). The Instagram connector is real code, not a stub, but
it's unverified against a live account — see
[docs/meta-setup.md](docs/meta-setup.md)'s "what's unverified" section.

## Project layout

```
app/
  rules/              # the 12 detectors + engine + context loader (the actual engine)
  ai/                 # single OpenRouter-calling function + template fallbacks
  metrics/            # 3-tier post-metrics provider (seeded/manual/instagram) + sync job
  intake.py           # deal intake: normalize / validate / commit a drafted brief (no AI import)
  campaign_intake.py  # campaign intake: same discipline as intake.py, at campaign scope
  reliability.py      # transparent weighted reliability-score formula, scoped per campaign
  dashboard.py        # aggregation layer between the engine and the screens, scoped per campaign
  actions.py          # decisions, campaign selection, per-campaign day clock
  api.py              # JSON API under /api (used by frontend/)
  main.py             # FastAPI app: HTML routes, /healthz, mounts the API
  templates/          # Jinja2 + HTMX server-rendered screens
frontend/                  # React + TS single-page app, deployed on Vercel (pre-campaigns screens only)
config/thresholds.yaml     # every rule threshold, severity, status cutoff, and intake default — editable
scripts/seed.py            # GlowLeaf (simulated clock) + LumaDerm (live clock, overlapping creators) + 6mo history
tests/                     # pytest: all 12 rules, contracts, deal/campaign intake, metrics connector, JSON API
tests/fixtures/meta/       # recorded Meta API response shapes the metrics connector is tested against
render.yaml                # Render Blueprint (free Docker web service)
.github/workflows/         # CI + keep-alive ping
docs/meta-setup.md         # Instagram connector: capability table, setup checklist, what's unverified
docs/designs/              # office-hours design doc + frontend brief
```
