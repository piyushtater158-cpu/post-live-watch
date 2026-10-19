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

## Running it locally

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

python scripts/seed.py --reset   # generates data/postlivewatch.db
pytest -v                        # 13/13 should pass — the correctness proof

cp .env.example .env              # optional: add OPENROUTER_API_KEY to enable AI
uvicorn app.main:app --reload --port 8420
```

Open `http://127.0.0.1:8420/`. Use the **Advance day ▶** control in the top nav to replay the 7-day campaign and watch flags appear over time (exactly what the day-simulator is for). Hit `/api/debug` directly for the full computed state as JSON — the same proof-of-correctness surface the tests check against.

Screens: Campaign Overview (`/`) · Flag Queue (`/queue`) · Creator Profiles (`/creators`) · Brand Daily Report (`/report`, read-only) · Decision Log (`/decisions`).

**AI on/off**: the pill button in the nav toggles `app_state.ai_enabled` in the DB. With no `OPENROUTER_API_KEY` set, every AI task function (`app/ai/provider.py`) falls back to its template/keyword counterpart automatically — nothing breaks.

## Frontend status

The current templates (`app/templates/*.html`) are functional but minimally styled — built to prove the engine and the full user flow (approve/edit/dismiss, day simulator, AI toggle, decision log) work end-to-end first. The real visual design is handed off separately per screen; see `docs/designs/frontend-brief.md` for the exact content/data contract each screen needs. See also `docs/designs/*-design-*.md` for the original build decisions (stack, hosting, rules-vs-AI split) from the planning session.

## Deploying (Oracle Cloud VM, alongside an existing n8n instance)

```bash
cp .env.example .env    # fill in OPENROUTER_API_KEY if you have one
docker compose up -d --build
```

This runs the app in a container with a persistent `./data` volume (so the SQLite DB, decision log, and day-simulator state survive restarts — the seed script only runs if `data/postlivewatch.db` doesn't exist yet). Point your existing reverse proxy (Caddy/nginx/Cloudflare Tunnel) at port `8420`. See `docker-compose.yml` for joining your n8n instance's Docker network if you wire up the optional report-delivery workflow below.

To update after a `git pull`: `docker compose up -d --build` again.

## Optional: n8n daily brand-report trigger

Not built by default (explicitly optional in the brief, and kept out of the critical path — see the design doc's reasoning on why n8n stays out of the rules/scoring pipeline entirely). If you want it: a scheduled n8n workflow hitting `GET /report` (or a future `GET /api/brand-report` JSON endpoint) and delivering the result via email/Slack/webhook.

## Out of scope

Real Instagram API, authentication, multi-tenant support, payments, auto-sending messages, mobile app — per the brief. Nothing here was attempted.

## Project layout

```
app/
  rules/          # the 12 detectors + engine + context loader (the actual engine)
  ai/             # single OpenRouter-calling function + template fallbacks
  reliability.py  # transparent weighted reliability-score formula
  dashboard.py    # aggregation layer between the engine and the screens
  main.py         # FastAPI routes
  templates/      # Jinja2 + HTMX (functional, pending design handoff)
config/thresholds.yaml   # every rule threshold, severity, and status cutoff — editable
scripts/seed.py           # synthetic GlowLeaf campaign + 20 creators + 6mo history
tests/                     # pytest suite verifying all 12 rules fire correctly
docs/designs/              # office-hours design doc + frontend brief
```
