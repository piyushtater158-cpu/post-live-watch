# Post-Live Watch — Interview Prep

A complete walkthrough of the system. Points marked **Likely question** are what an interviewer is most likely to ask, each with a short answer you can give.

---

## 1. What the system is

**Post-Live Watch** is a triage dashboard for an influencer-marketing account manager (Confluencr-style). After an Instagram campaign goes live, the manager has 20–100 creator posts to check against what each creator promised. Today that is done by hand in spreadsheets and WhatsApp.

The system:

1. Checks every post for **12 named problems**.
2. Sorts each post into **Act now**, **Needs a look**, or **OK**.
3. Suggests a message to send to the creator.
4. Lets the manager **Approve, Edit, or Dismiss** that message, and logs the decision with a timestamp.

All data is sample data: a fictional skincare brand (GlowLeaf), 20 creators, one 7-day campaign with 20 posts (8 healthy, the rest problems plus one viral winner), and 6 months of history per creator. Nothing auto-sends. The manager copies the message and sends it.

> **Likely question:** "Who is the user, and what problem does this solve?"
>
> One account manager after launch. It replaces manual spreadsheet checking with automatic flags, a priority order, and a ready-to-send message.

---

## 2. The core design idea: rules first, AI on top

This is the most important point to explain well.

- Every flag comes from a **deterministic Python rule** in `app/rules/detectors.py`.
- Every threshold lives in **one editable file**, `config/thresholds.yaml`: grace days, late hours, reach percentages, sentiment keywords, severities, and status cutoffs.
- **AI never decides whether something is a problem.** It only adds language on top of a rule that already fired:
  - explains why a post underperformed,
  - reads Hinglish and sarcastic comments,
  - adds a note on possibly paraphrased banned claims,
  - suggests a boost for viral posts,
  - drafts nudge messages, brand alerts, and the daily brand report.
- If AI is off, the API key is missing, or the call fails, every AI function **falls back to a template**, and the app still works end to end.

> **Likely question:** "Why not just let an LLM flag the problems?"
>
> Rules are explainable, reproducible, testable, and cost nothing to run. An account manager or a brand can ask "why was this flagged?" and the answer is a number in a config file. LLMs can be non-deterministic and hallucinate, and you cannot write a reliable test that "rule X fires on post Y" against one. AI is used only where language understanding really helps, like Hinglish and sarcasm.

> **Likely question:** "What happens if OpenRouter is down?"
>
> `call_ai()` in `app/ai/provider.py` catches every exception and returns `None`. Each task function then returns its template text from `app/ai/templates.py`. This is tested in `tests/test_ai_fallback.py`.

> **Likely question:** "How do you switch AI models?"
>
> Set the `OPENROUTER_MODELS` environment variable: a comma-separated list in preference order. No code change is needed.
>
> The app uses **free OpenRouter models only**, for example Nemotron 3 Super, Gemma 4, and the `openrouter/free` router as a last resort. Two guards stop a paid request:
>
> - The code drops any model id that isn't a `:free` variant.
> - Every request sends `provider.max_price = 0`, so OpenRouter refuses any endpoint that costs money.
>
> OpenRouter accepts at most 3 models per request, so the list is tried in groups of 3.
>
> **Likely follow-up:** "What about the free-tier quota?" Free models allow about 20 requests a minute and 50 a day. Answers are cached per prompt, and the current day's notes are generated in the background after startup or a day change. If OpenRouter reports an account rate limit, every AI call falls back to templates until the limit resets.

---

## 3. Architecture and request flow

The request path, from top to bottom:

1. **Browser** — the React single-page app in `frontend/` (served by Vercel), or the Jinja2 + HTMX pages served directly by FastAPI. Both show the same screens.
2. **`app/api.py`** (JSON, under `/api`) and **`app/main.py`** (HTML pages) — FastAPI routes. Both call the same helpers in **`app/actions.py`** for decisions and the day simulator, so the two surfaces can't drift apart.
3. **`app/dashboard.py`** — combines data for each screen.
4. **`app/rules/engine.py`** — runs all 12 detectors on each post and computes the status.
5. **`app/rules/context.py`** — loads one post's data as of the current simulated day.
6. **`app/rules/detectors.py`** — the 12 rule functions, reading `config/thresholds.yaml`.
7. **`app/ai/provider.py`** — the single OpenRouter call, with fallback to `app/ai/templates.py`.
8. **SQLite** — raw `sqlite3`, no ORM.

**Stack:** FastAPI, SQLite, OpenRouter on the backend; React + TypeScript (Vite) on the frontend; the original Jinja2 + HTMX pages are still served by FastAPI.

**Deployment ($0):**

- **API on Render's free plan**, built from the `Dockerfile` using the `render.yaml` Blueprint.
- **Frontend on Vercel.** `frontend/vercel.json` forwards `/api/*` to Render, so the browser only ever talks to one origin and the backend needs no CORS setup.
- **Keep-alive ping.** Render's free plan sleeps after 15 idle minutes and wipes the filesystem, including the SQLite file, when it does. A GitHub Actions job (`.github/workflows/keepalive.yml`) pings `/healthz` every 10 minutes during Indian daytime (08:30 to 00:30 IST) to keep it awake. That's about 500 of the 750 free hours a month. The hours are shared across the whole Render workspace, and going over suspends every free service, so the rest is left for the other service.
- **Self-hosted fallback.** `docker compose up -d --build` still works on any VM with a persistent `./data` volume.

**Screens:** Campaign Overview (`/`), Flag Queue (`/queue`), Creator Profiles (`/creators`), Brand Daily Report (`/report`), Decision Log (`/decisions`), and the raw engine output at `/api/debug`.

> **Likely question:** "Your data lives in SQLite on a free host with an ephemeral disk. Isn't that fragile?"
>
> Yes, deliberately. All the data is synthetic and re-seeded from `scripts/seed.py`, so losing it only resets the demo to day 1, which the Reset button already does. The keep-alive stops idle restarts from wiping it, so only a redeploy resets it. For real customer data I'd move to managed Postgres; the rest of the app wouldn't change, because all SQL sits behind `app/db.py`, `app/actions.py` and the dashboard layer.

> **Likely question:** "Why SQLite and not Postgres?"
>
> The scale is one user, about 20 creators, at most 100 posts, a few thousand rows, and no concurrent writers. Postgres would add a service to run with no correctness benefit. A single file also makes resets and the day simulator trivial. I would move to Postgres when there are multiple account managers writing at the same time, or multiple tenants.

> **Likely question:** "Why not build the pipeline in n8n?"
>
> n8n has no real testing story, and the main requirement was proving all 12 rules fire correctly with `pytest`. The thresholds belong in one YAML file, not scattered across node settings. The data is relational and needs joins. n8n is allowed only as an optional scheduled trigger to deliver the daily brand report.

> **Likely question:** "Why no ORM?"
>
> The data model is small, and plain SQL keeps it transparent and easy to inspect.

> **Likely question:** "Why is there both HTMX and React?"
>
> The first version was server-rendered with HTMX, so the time went to the rules engine instead of an API, a JS build and CORS. Once the engine was proven, the frontend moved to a React app on Vercel so it could be deployed and scaled separately from the API. The JSON API returns exactly the dicts the templates already rendered, so the move was mechanical. Vercel's rewrite to Render means no CORS. The HTMX pages stay as a fallback and are covered by the same tests.

---

## 4. Data model (`app/schema.sql`)

- **`brands`** have **`campaigns`**. A campaign stores the required disclosure, tag, hashtag, link-sticker requirement, and banned claims.
- A campaign has **`deliverables`**. Each links a creator, a format (reel, carousel, or story), a fee, a promised date, and a minimum reach.
- Each deliverable has a **`posts`** row: caption, original approved caption, edit time, link sticker, whether it is a story, and whether a screenshot was uploaded.
- Each post has **`post_snapshots`**, one per day: reach, likes, comments, saves, shares, and whether the post is still live.
- Each post has **`comments`**, each tagged with a day and a language (`en` or `hi-en` for Hinglish).
- Each creator has **`historical_campaigns`**, which feed the reliability score.
- **`flags`** and **`decisions`** form the audit trail.
- **`app_state`** stores the current simulated day and the AI on/off toggle.

> **Likely question:** "Are flags stored or computed?"
>
> They are **computed live** on every request. A flag row is written to the database only when a person acts on it, so the decision log can point to the exact flag that was decided.

---

## 5. The 12 detectors

Each detector is a **pure function**: it takes a post's context and the thresholds, and returns either a flag (rule id, name, polarity, severity, reason, evidence) or `None`.

| # | Rule | How it fires |
|---|---|---|
| 1 | Not posted | No post after the due day plus a 1-day grace |
| 2 | Posted late | More than 6 hours after the promised time |
| 3 | Missing disclosure | Caption lacks `#ad` or "paid partnership" |
| 4 | Missing tag / hashtag / link | Brand tag, hashtag, or link sticker missing |
| 5 | Underperforming | Reach below 70% of the promise **and** below 60% of the creator's average |
| 6 | Suspicious engagement | Comment-to-like ratio outside 0.015–0.25, or likes jump more than 4x in a day |
| 7 | Negative sentiment | 3 or more keyword hits, or 20% or more of comments (English and Hinglish keywords) |
| 8 | Deleted early | Post was live, then disappeared before the campaign ended |
| 9 | Caption edited off-brief | Edited after approval and now contains a banned claim |
| 10 | Story without proof | Story older than 24 hours with no screenshot |
| 11 | Competitor post | Competitor mention within 3 days of the due date |
| 12 | Viral winner (positive) | Reach of 2.2x the creator's average or more |

> **Likely question:** "Why does underperforming need both conditions?"
>
> To avoid false alarms. A small creator who missed an over-ambitious promise but performed normally for them is not really underperforming.

> **Likely question:** "How does the sentiment rule handle 'this is not fake'?"
>
> It does not. Keyword matching cannot handle negation or sarcasm. That is exactly why AI classification is added on top as a second opinion. It adds a summary but does not change whether the flag fires.

> **Likely question:** "Why compare comments to likes?"
>
> Bought likes give very few comments per like. Comment pods and bots give unusually many. Both fall outside a normal range.

> **Likely question:** "How would you add a 13th rule?"
>
> Write one new function in `detectors.py`, add its thresholds and severity to `thresholds.yaml`, add it to `ALL_DETECTORS`, seed a post that should trigger it, and add a test case. Nothing else changes.

---

## 6. Status, severity, and the viral-winner case

Each rule has a severity from 1 to 9 in `thresholds.yaml`. A post's status comes from the **highest severity among its negative flags only**:

- 7 or more → **Act now**
- 4 to 6 → **Needs a look**
- below 4 → **OK**

The viral winner is **positive**, so it goes into a separate `opportunities` list. A post can be "OK" and still appear in the queue as an opportunity. There is a test for exactly this.

> **Likely question:** "Why use the max severity instead of adding them up?"
>
> It is simple and explainable: the worst problem decides urgency. Adding them up would let several minor issues outrank one critical one, like a deleted post. A fair improvement would be a tie-breaker based on the number of flags.

---

## 7. The day simulator

All 7 days of data are seeded up front. `load_post_context` only loads snapshots and comments where `day_number <= current_day`. Time-based rules use `as_of`, which is the end of the current day.

Pressing **Advance day** increments a counter in `app_state`, and flags appear over time. For example, "Not posted" fires only on day 3, after the grace period, and the story rule fires only after 24 hours. Both are tested.

> **Likely question:** "How would this work with real data?"
>
> Replace the seed with a scheduled job that pulls metrics from the Instagram Graph API and stores one snapshot row per post per day. The engine does not change, because it only reads snapshots up to a given day.

---

## 8. Reliability score (`app/reliability.py`)

```
score = 100 × ( 0.40 × on_time_rate
              + 0.25 × min(avg_performance_ratio, 1.2) / 1.2
              + 0.20 × (1 − min(avg_flags_per_campaign / 3, 1))
              + 0.15 × (1 − competitor_conflict_rate) )
```

It combines 6 months of history with the current campaign.

- 75 or more → "Yes — book again"
- 50 to 74 → "Maybe — review flags first"
- below 50 → "Caution — review before rebooking"

> **Likely question:** "Why these weights?"
>
> On-time delivery matters most to an agency, so it gets 40%. Performance is capped at 1.2x so one viral post cannot hide bad behaviour. Be honest that the weights are a reasoned first draft and should be tuned against real rebooking outcomes.

---

## 9. Approval flow and audit trail

`POST /api/flags/{post_id}/decide` (JSON, used by the React app) and `POST /flags/{post_id}/decide` (form post, used by the HTMX page) both call `record_decision` in `app/actions.py`. It handles three actions:

- **Approve** — stores the suggested message exactly as written.
- **Edit** — stores what the manager typed.
- **Dismiss** — stores no message.

Each decision is saved with a UTC timestamp, and the endpoint returns the refreshed queue, which the React app re-renders (or HTMX swaps in). `/decisions` shows the full log.

> **Likely question:** "Why log decisions?"
>
> Accountability and future learning. You can measure how often the manager edits or dismisses AI suggestions, which tells you whether the AI is useful and whether a threshold is too sensitive.

> **Likely question:** "Why does nothing auto-send?"
>
> A human stays in the loop for anything that reaches a creator or brand. That protects against a wrong flag or a bad AI message going out under the agency's name.

---

## 9b. Deal intake: the one place AI does real work

**New Deal** (`/intake`) turns a manager's shorthand note into real creator, deliverable and post rows. For example: "Signed Priya for 2 reels + 1 story, barter worth ₹5k, no reach guarantee, skipping our hashtag, due in 3 days".

The flow:

1. **Draft.** AI produces a JSON draft. With AI off, a keyword extractor produces the same shape.
2. **Check.** `app/intake.py` normalises and validates the draft without trusting it.
3. **Review.** The manager sees an editable preview, including the exact contract notes the queue will later show.
4. **Confirm.** Nothing is saved until the manager approves, edits or dismisses, the same pattern as the Flag Queue.

> **Likely question:** "Isn't letting AI write rows the engine reads dangerous?"
>
> Yes. That's why it's fenced on four sides:
>
> - **Approval.** A person always approves.
> - **Validation.** The output is validated like untrusted input.
> - **No invented numbers.** The AI is forbidden from emitting average reach or engagement. Those come from a follower-count estimate in config and are labelled "Estimated reach".
> - **No compliance waivers.** Disclosure can never be waived through intake. A mis-read sentence would otherwise switch off the compliance rule.
>
> A mis-read "no reach guarantee" shows up in the preview as a visible contract note before anything is saved.

> **Likely question:** "What does a brand-new creator's reliability score look like?"
>
> There isn't one: "New — no track record yet". Until their first deliverable is due, there's no evidence to score. A barter deal with no reach guarantee is also left out of the performance average rather than counted as 0x.

---

## 10. Testing

There are 92 `pytest` tests, and CI (`.github/workflows/ci.yml`) runs them plus the frontend build on every push.

- `tests/test_rules.py` maps each problem post to its expected rule. It checks that all 12 rules fire, that the 8 healthy posts stay clean, that the viral winner is not hidden, that the grace period and the 24-hour window are respected, and that severity ordering is correct.
- `tests/test_reliability.py` checks the reliability score.
- `tests/test_ai_fallback.py` checks that every AI function still returns usable text when AI is off.
- `tests/test_contract.py` checks that negotiated deal terms override the campaign brief.
- `tests/test_api.py` checks every JSON endpoint the React app uses, the simulator controls, and the full approve / edit / dismiss flow, including approving a viral-winner card that has no problem flags.

`/api/debug` returns the full computed state as JSON, so a reviewer can check the engine without clicking through screens.

> **Likely question:** "Why build the engine before the UI?"
>
> The hardest thing to verify, rule correctness, was built first while time and attention were freshest. If time had run out, there would still be a proven engine.

---

## 11. Weak spots to prepare for

Interviewers often probe here. Admitting a weak spot clearly and explaining the fix scores better than defending it.

1. **Disclosure is hardcoded.** Rule 3 checks for `#ad` and "paid partnership" directly in code. The campaign's `required_disclosure` is used only in the message text. That contradicts "nothing hardcoded". *Fix:* read the accepted labels from the campaign or the YAML.
2. **Reliability weights live in Python, not in `thresholds.yaml`.** Again, not fully "one config file". *Fix:* move them into the YAML.
3. **Single campaign only.** `campaign_id=1` and `duration_days=7` are hardcoded in `app/actions.py`, `app/api.py` and `dashboard.py`. *Fix:* read them from the campaign row and add a campaign selector.
4. **Flag evidence is saved as Python text, not JSON.** `str(match["evidence"])` in `app/actions.py` writes Python's own text format, which is not valid JSON, although the schema says JSON. *Fix:* use `json.dumps`.
5. **Performance.** AI calls are synchronous, one per flag, inside the page request, each with a 15-second timeout, and nothing is cached. A slow provider makes the queue page slow. The engine also runs several times per request, with many small queries. *Fix:* cache AI output per flag and day, generate it in the background, and batch the queries.
6. **One post per creator** is assumed (`fetchone()` in the reliability and dashboard code). *Fix:* aggregate over all of a creator's posts.
7. **No authentication or CSRF protection.** Explicitly out of scope for the brief, but worth saying you know it is needed.
8. **Prompt injection.** Comment text goes straight into the LLM prompt. The risk is low because the output is only shown to a person and nothing auto-sends.
9. **Deprecated startup hook.** `@app.on_event("startup")` is deprecated in newer FastAPI versions in favour of lifespan handlers. Minor.

> **Likely question:** "What would you do with another week?"
>
> Move every weight and keyword list into config, support multiple campaigns, add caching and background AI generation, connect the real Instagram Graph API, add authentication, and use the decision log to tune thresholds.

---

## 12. How to demo it

1. Run `pytest -v` and show all 92 passing.
2. Open [post-live-watch.vercel.app](https://post-live-watch.vercel.app) (or `/` locally) on day 1 and press **Advance day** a few times. New flags appear.
3. Open `/queue`, approve one message, edit another, then show `/decisions`.
4. Toggle AI off and show the app still works with template text.
5. Open `/api/debug` to show the raw engine output.

---

## 13. One-minute pitch

> "Post-Live Watch helps an influencer agency's account manager check every creator post after a campaign goes live. It runs 12 transparent rules, all driven by one config file, to flag problems like missing disclosures, late posts, fake engagement, or negative comments, and ranks posts into Act now, Needs a look, or OK. AI sits on top only to explain and write messages. It never decides what's a problem, and the whole app still works with AI turned off. A human approves every message, and every decision is logged. The engine was built and tested first: a pytest suite proves all 12 rules fire on exactly the right posts."
