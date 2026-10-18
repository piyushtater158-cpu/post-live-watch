# Post-Live Watch — Frontend Design Brief (for Claude Design handoff)

This is the content/data/interaction spec for each screen. The backend is
already built and running on functional (unstyled) Jinja2 + HTMX templates
at `app/templates/*.html` — this brief is what gets redesigned; the data
contracts below don't change, only the markup/CSS wrapping them.

**Visual tone**: operational dashboard for a marketing agency account
manager — think "mission control for a live campaign," not a marketing
site. Status (OK / Needs a look / Act now) must be instantly scannable by
color. Every screen carries a persistent "SAMPLE DATA" indicator (brief
requirement — all data is synthetic).

**Global chrome (every screen)**
- Top nav: app name, links to the 5 screens below.
- AI on/off toggle (pill button, shows current state).
- Day indicator ("Day N/7") + "Advance day ▶" button + "Reset to day 1".
- These three controls are global state — changing them affects every screen.

---

## 1. Campaign Overview (`/`, template `index.html`)
**Content inventory**: page title "GlowLeaf Vitamin C Serum Launch — Campaign Overview", 6 KPI tiles, one sortable table.

**Data fields**:
- KPI tiles: `posts_live`/`total_due` (e.g. "14/20"), `total_reach`/`total_promised` (formatted with commas), `by_status["Act now"]`, `by_status["Needs a look"]`, `by_status["OK"]`, `opportunities` (viral count).
- Table rows (`rows`, one per post): `creator_handle` (links to profile), `format` (reel/carousel/story), `status` chip, `max_severity` (int), `reason` (one-line string).

**Interaction states**: table sortable by any column (client-side is fine); status chip color-coded (red=Act now, amber=Needs a look, green=OK); row hover highlights.

**Empty/edge states**: day 1 with nothing posted yet (most rows "OK" with low reach, a few "Act now" for anything already overdue — unlikely at day 1 given 1-day grace).

---

## 2. Flag Queue (`/queue`, template `queue.html`)
**Content inventory**: "Flag Queue (Act now first)", a stack of flag cards, no cards when clean.

**Data fields per card** (`cards`, pre-sorted Act-now-first):
- `status` chip, `handle`, `format`, `max_severity`.
- `flags[]`: each has `rule_name`, `rule_id`, `severity`, `reason`, optional `ai_note` (shown only when AI is on and had something to add — e.g. Hinglish sentiment summary, paraphrase-claim note, underperformance explanation).
- `opportunity_note`: present only for viral-winner posts (rule 12) — render as a distinct "🚀 viral winner" callout, visually separate from problem flags (different color, e.g. blue, not red/amber).
- `suggested_message`: AI- or template-generated copy-paste text (creator nudge).

**Interaction states**:
- Each card's action row: **Approve** / **Edit & Approve** / **Dismiss** buttons, plus an editable textarea pre-filled with `suggested_message` and a **Copy** button (clipboard).
- Submitting any action POSTs to `/flags/{post_id}/decide` and the card list re-renders (currently HTMX partial swap of `#queue-list` — keep this swap target id if redesigning the HTML, or tell the backend team the new target id).
- Empty state: "No flags right now — everything's clean as of day {N}."

---

## 3. Creator Profile (`/creators/{id}`, template `creator_profile.html`; list at `/creators`, template `creators.html`)
**Content inventory**: creator handle + tier/niche, 4 KPI tiles, a "book again?" hint line, current-campaign status, a 12-month history table.

**Data fields**:
- KPI tiles: `reliability.score` (0-100), `reliability.on_time_rate` (as %), `reliability.avg_performance_ratio` (as "x"), `reliability.avg_flags_per_campaign`.
- `reliability.book_again_hint`: one of "Yes — book again" / "Maybe — review flags first" / "Caution — review before rebooking" — style as a clear colored banner/pill (green/amber/red respectively).
- `current_campaign`: status chip + reason for the live GlowLeaf post (omit section if creator has no post this campaign — shouldn't happen, all 20 have one).
- `reliability.history[]`: rows of `month`, `campaign_name`, `delivered_on_time` (bool), `performance_ratio`, `flags_count`, `fix_speed_days` (nullable), `competitor_conflict` (bool), `outcome`.

**Interaction states**: history table — highlight rows with `competitor_conflict=true` or `outcome != "completed"` distinctly.

---

## 4. Brand Daily Report (`/report`, template `report.html`)
**Content inventory**: a read-only, brand-facing page. "GlowLeaf — Daily Report (read-only, brand view)", a narrative text block, highlights list, issues list.

**Data fields**: `text` (3-5 sentence AI-written or template narrative), `highlights[]` (strings), `issues[]` (strings, empty list renders "None.").

**Visual tone shift**: this is the one screen a brand client sees — should read calmer/more polished than the AM's operational screens, less "ops dashboard," more "status update email rendered as a page." Still needs the SAMPLE DATA banner.

---

## 5. Decision Log (`/decisions`, template `decisions.html`)
**Content inventory**: a plain audit table — every approve/edit/dismiss action ever taken, with timestamp.

**Data fields**: `created_at`, `creator_handle`, `rule_name` (nullable — dismiss-without-flag edge case), `action` (approve/edit/dismiss, color-coded chip), `message_text` (nullable).

**Interaction states**: none beyond display — this is a pure audit trail, newest first.

---

## Handoff format requested
Static HTML + CSS per screen (5 files: overview, queue, creator-profile incl. list, report, decisions), using the exact data field names above as placeholder content so the conversion to Jinja2 is mechanical (loop/conditional insertion, not re-deriving structure). Once returned, conversion work is: swap placeholder content for `{{ jinja_expr }}` / `{% for %}` tags and re-attach the two `hx-post` interactions (decide form, and the three global-chrome POSTs) — no backend logic changes.
