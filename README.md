# Post-Live Watch

A post-live campaign triage dashboard for Confluencr-style influencer marketing — proof-of-work for the Walnut Folks Group "AI Product Engineer" role. The JD asks for "AI workflows that screen, score or summarise campaign data"; this is a working one.

**All data is SAMPLE DATA.** A fictional skincare brand (GlowLeaf), 20 fictional creators, synthetic metrics. No real Instagram API, no real accounts.

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

## Running it locally

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

python scripts/seed.py --reset   # generates data/postlivewatch.db
pytest -v                        # all 92 should pass — the correctness proof

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

Screens: Campaign Overview (`/`) · Flag Queue (`/queue`) · Creator Profiles (`/creators`) · Brand Daily Report (`/report`, read-only) · Decision Log (`/decisions`) · New Deal (`/intake`).

**AI on/off**: the pill button in the nav toggles `app_state.ai_enabled` in the DB. With no `OPENROUTER_API_KEY` set, every AI task function (`app/ai/provider.py`) falls back to its template/keyword counterpart automatically — nothing breaks.

## Frontend

There are two frontends for the same screens. Both read the same data from `app/dashboard.py`, so they can't disagree.

- **`frontend/`**: the deployed one. React + TypeScript (Vite + React Router), styled with the Claude Design stylesheet (`app/static/app.css`, copied as-is). It talks only to the JSON API in `app/api.py`.
- **`app/templates/`**: the original server-rendered Jinja2 + HTMX pages, still served by FastAPI at the API's own URL.

See `docs/designs/frontend-brief.md` for the content and data contract of each screen.

JSON API (all under `/api`):

- `GET`: `state`, `overview`, `queue`, `creators`, `creators/{id}`, `report`, `decisions`, `intake` (campaign defaults), `debug`.
- `POST`: `flags/{post_id}/decide` (JSON body: `action`, `message_text`, `original_message`, `flag_rule_id`), `simulate/advance-day`, `simulate/reset-day`, `settings/ai-toggle`.
- `POST` (deal intake):
  - `intake/parse` takes `{brief_text}` and returns the draft and its blocking errors, without writing anything.
  - `intake/confirm` takes `{action, original_draft, draft}`. Approve commits `original_draft`, edit commits `draft`, and dismiss writes nothing.
- `GET /healthz` returns `{"ok": true}`.

## Deploying ($0: Render + Vercel + GitHub Actions)

```
Browser ──> Vercel (frontend/, static React build)
              └─ rewrite /api/* ──> Render free web service (Dockerfile: FastAPI + SQLite)
GitHub Actions keep-alive ──(every 10 min, IST daytime)──> Render /healthz
```

- **API on Render**, defined in `render.yaml`: Docker runtime, `free` plan, health check on `/healthz`, auto-deploys on pushes to `main`.
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

### Self-hosted alternative (any VM with Docker)

```bash
cp .env.example .env    # fill in OPENROUTER_API_KEY if you have one
docker compose up -d --build
```

This runs the API and the server-rendered screens with a persistent `./data` volume, so the SQLite DB, decision log, and day-simulator state survive restarts. The seed script only runs if `data/postlivewatch.db` doesn't exist yet. Point a reverse proxy (Caddy, nginx or Cloudflare Tunnel) at port `8420`. To update after a `git pull`, run `docker compose up -d --build` again.

## Optional: n8n daily brand-report trigger

Not built by default (explicitly optional in the brief, and kept out of the critical path — see the design doc's reasoning on why n8n stays out of the rules/scoring pipeline entirely). If you want it: a scheduled n8n workflow hitting `GET /report` (HTML) or `GET /api/report` (JSON) and delivering the result via email/Slack/webhook.

## Out of scope

Real Instagram API, authentication, multi-tenant support, payments, auto-sending messages, mobile app — per the brief. Nothing here was attempted.

## Project layout

```
app/
  rules/          # the 12 detectors + engine + context loader (the actual engine)
  ai/             # single OpenRouter-calling function + template fallbacks
  intake.py       # deal intake: normalize / validate / commit a drafted brief (no AI import)
  reliability.py  # transparent weighted reliability-score formula
  dashboard.py    # aggregation layer between the engine and the screens
  actions.py      # decisions + day simulator, shared by both route sets
  api.py          # JSON API under /api (used by frontend/)
  main.py         # FastAPI app: HTML routes, /healthz, mounts the API
  templates/      # Jinja2 + HTMX server-rendered screens
frontend/                  # React + TS single-page app, deployed on Vercel
config/thresholds.yaml     # every rule threshold, severity, and status cutoff — editable
scripts/seed.py            # synthetic GlowLeaf campaign + 20 creators + 6mo history
tests/                     # pytest: all 12 rules, contracts, deal intake, AI fallback + free-model guard, JSON API
render.yaml                # Render Blueprint (free Docker web service)
.github/workflows/         # CI + keep-alive ping
docs/designs/              # office-hours design doc + frontend brief
```
