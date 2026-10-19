# Post-Live Watch — frontend handoff

Static HTML + one shared CSS/JS. Every value that comes from the backend is
marked with `data-field="<exact field name from the brief>"`, and every loop or
conditional has a `<!-- for … -->` / `<!-- if … -->` comment. Converting to Jinja2
means swapping the sample content for `{{ … }}` / `{% for %}` tags. No backend
logic changes, except the two items marked **BACKEND** below.

## Files → templates

| Handoff file | Replaces | Notes |
|---|---|---|
| `static/app.css` | new `static/app.css` | Holds all styles. The templates have no `<style>` blocks |
| `static/app.js` | new `static/app.js` | Table sort, copy button, Edit & Approve enable logic. Survives HTMX swaps |
| *(chrome block)* | `base.html` | Copy the `BEGIN/END global chrome` block from any AM page |
| `overview.html` | `index.html` | |
| `queue.html` | `queue.html` | Keep `id="queue-list"`. The empty state is commented out at the bottom |
| `creators.html` | `creators.html` | Columns are **assumed** (see below) |
| `creator_profile.html` | `creator_profile.html` | |
| `report.html` | `report.html` | Does **not** extend `base.html`. Use a separate `base_brand.html` |
| `decisions.html` | `decisions.html` | |

## Fixes applied

1. **Plain HTML + CSS.** No canvas wrapper and no inline style blocks. Classes come from one stylesheet.
2. **Approve vs Edit & Approve.** Each form now posts `original_message` (= `default_message`) next to `message_text`.
   - `approve` → JS resets the textarea to the original, so the suggestion is sent exactly as written.
   - `edit` → the button stays disabled until the text differs from the original.
   - **BACKEND:** decide on `action`. For `approve`, store `original_message`. For `edit`, store `message_text`. The backend must also accept the new `original_message` form field.
3. **Status sort order.** Cells carry `data-sort-value`: Act now = 3, Needs a look = 2, OK = 1. Severity and score use their numbers. `app.js` sorts on these values, not on the visible text.
4. **Brand report.** The page has no AM nav or controls. A small agency-only preview bar links back to the dashboard. Remove that bar if the URL is ever sent to the brand.
5. **`/creators` columns (assumed):** `handle`, `tier`, `niche`, `reliability.score`, `reliability.book_again_hint`, `current_campaign.status`. Drop any column the list view doesn't provide.
6. **Global-chrome endpoints.** The buttons post to `/__TODO__/ai/toggle`, `/__TODO__/day/advance` and `/__TODO__/day/reset`. Grep for `__TODO__` and replace them with the real routes. Reset now asks for confirmation (`hx-confirm`).
7. **Severity range.** The meter assumes 0–5: 5 bars, with `class="on"` for `i < min(max_severity, 5)`. `.sev0`–`.sev5` style the severity badge in the queue.

## Class mappings used in loops

- Status → `act` / `look` / `ok` (chips, card `.strip`). Opportunity → `opp`.
- `book_again_hint` → `yes` / `maybe` / `caution` (`.hint` on the list, `.verdict` on the profile).
- History row → add `conflict` if `competitor_conflict`. Add `incomplete` if `outcome != "completed"`.
- Decision `action` → `a-approve` / `a-edit` / `a-dismiss`.
- `ai` button → `aria-pressed="true|false"`, label `ON|OFF`.
- Day pips → 7 `<i>`, with `class="on"` for `i < day`.

## Prompt for Claude Code

> Convert the static designs in `handoff/` into our Jinja2 + HTMX templates in `app/templates/`.
> Read `handoff/README.md` first and follow its file mapping and class mappings exactly.
> Move `handoff/static/app.css` and `app.js` into our static folder and link them from `base.html`.
> Build `base.html` from the global chrome block. Every AM page extends it. `report.html` uses a new `base_brand.html` with only the SAMPLE DATA strip.
> Replace each `data-field` sample value with the matching context variable (the field names are exact). Turn the `<!-- for/if -->` comments into real tags, keep one sample row per loop, and delete the rest.
> Keep `id="queue-list"` and the decide form's `hx-post="/flags/{{ post_id }}/decide" hx-target="#queue-list"`.
> Update the decide handler: `action=approve` stores `original_message`, `action=edit` stores `message_text`, `dismiss` stores no message.
> Replace the `/__TODO__/…` routes with our existing AI-toggle and day endpoints. Show me the diff of each template before writing it.
