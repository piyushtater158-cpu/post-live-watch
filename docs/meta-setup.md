# Instagram connector setup

`app/metrics/instagram.py` can pull real post metrics for a campaign whose
`metrics_provider` is `'instagram'`. Nothing in this app requires it — every
screen works on seeded or manually-entered numbers — but turning it on
upgrades 7 of the 12 rule-based problem detectors from "whatever an account
manager types in" to "pulled from Meta."

As of writing (Oct 2026), **no Meta app exists for this project yet.** The
connector is built and tested against recorded response fixtures
(`tests/fixtures/meta/`), not a live token — this document is the checklist
for the day that changes.

## What's actually reachable, and what isn't

| Tier | What it needs | What it returns | Reach? |
|---|---|---|---|
| **Branded content** | Brand tagged as paid partner on the post + `instagram_branded_content_ads_brand` | likes, comments, views, reach, shares, saves | **Yes** |
| **Public** (`business_discovery`) | Only `instagram_basic` | caption, like count, comment count, timestamp, permalink | No |
| **Manual** | Nothing — an account manager types it in | Whatever was typed | Only if typed |

Not obtainable on **any** tier, from Meta or anyone else short of the
creator's own cooperation:

- **Comment text** on someone else's post (rule 7, Negative sentiment, needs
  manual entry or the creator's own screenshot).
- **Story insights** (rule 10, Story expired without proof — Instagram does
  not expose another account's Stories through any public or partner API).

This is why a creator skipping the `#ad`/"Paid Partnership" label costs them
twice: it trips rule 3 (Missing disclosure) **and** drops their post's data
from the branded-content tier down to the public one, where reach
disappears. The incentive to tag correctly and the data payoff for tagging
correctly are the same lever.

### Rule coverage by tier

| Rule | Branded content | Public | Manual |
|---|---|---|---|
| 1 Not posted | yes | yes | yes |
| 2 Posted late | yes | yes | yes |
| 3 Missing disclosure | yes | yes | yes |
| 4 Tag/hashtag | yes | yes | yes |
| 4 Link sticker | no (Story-only; Stories are invisible to both tiers) | no | yes |
| 5 Underperforming | **yes** | no — no reach | yes |
| 6 Suspicious engagement | yes | yes | yes |
| 7 Negative sentiment | no — no comment text | no | yes |
| 8 Deleted/archived early | yes | yes | yes |
| 9 Caption edited | yes | yes | yes |
| 10 Story expired without proof | no — Stories invisible | no | yes |
| 11 Competitor post | yes | yes | yes |
| 12 Viral winner | **yes** | no — no reach | yes |

A post whose only metrics source is the public tier gets a `data_notes` entry
on its card (`app/rules/engine.py`) explaining the gap instead of silently
scoring as if reach were zero.

## Setup checklist

1. **Create a Meta app** at [developers.facebook.com](https://developers.facebook.com) —
   type **Business**. Note the App ID and App Secret.
2. **Business Portfolio.** The app needs to live inside a Meta Business
   Portfolio (Business Manager). If the agency doesn't have one, create it
   and complete **Business Verification** — required for production access
   to branded-content permissions, not just App Review.
3. **System user token.** Inside the Business Portfolio, create an **Admin**
   system user, generate a token for it scoped to this app, and grant it
   `business_management` plus the Instagram permissions below.
4. **The brand shares its assets.** The brand's own Business Portfolio adds
   the agency's portfolio as a **Partner** and shares:
   - their IG Professional (Business or Creator) account
   - the Facebook Page linked to it
5. **Request App Review** for:
   - `instagram_branded_content_ads_brand` — reads posts where the brand is
     tagged as a paid partner, via the Partnership Ads Advertisable Content
     API (`GET /{business_id}/partnership-ads-advertisable-content`).
   - `instagram_basic` — the public `business_discovery` fallback tier; this
     one does not gate behind the same review queue.
6. **Set the environment variables** (`.env` / `.env.example`):
   ```
   META_BUSINESS_ID=         # the agency's own Business Portfolio id
   META_IG_BUSINESS_ID=      # the brand's IG Professional account id
   META_SYSTEM_USER_TOKEN=   # the Admin system user token from step 3
   META_GRAPH_VERSION=v21.0  # optional, defaults to v21.0
   ```
7. **Set the campaign's `metrics_provider` to `'instagram'`** (via
   `/campaigns/{id}/edit` or directly) and hit **Sync now** on `/campaigns`,
   or `POST /api/campaigns/{id}/sync`.

Without step 5 clearing, branded-content calls fail and
`app/metrics/instagram.py` degrades to the public tier automatically — the
app still runs, just with reach gone for any post that tier can't reach.

## What's unverified until a real token exists

Three things this connector assumes, flagged honestly because none of them
can be checked without a live token:

1. **Whether Development Mode grants any branded-content access before App
   Review clears.** The permissions reference reads as "no" — assumed no.
2. **Whether comment text is reachable for a tagged branded-content post
   specifically** (as opposed to public posts, where it clearly isn't) —
   assumed no.
3. **Whether Story insights reach the tagged brand** through the
   branded-content grant — assumed no.

All three are assumed **no** and routed to the manual-entry path. If any
turns out to be a yes, it's an upgrade to make, not a bug to fix — the
`data_notes` mechanism and the rule-coverage table above are exactly the
places that change.

## Running against fixtures instead of a live token

`tests/fixtures/meta/*.json` hold hand-written response shapes matching
Meta's documented schema (verified against the live docs as of Oct 2026 —
see `app/metrics/instagram.py`'s module docstring for the exact endpoints).
`tests/test_metrics_providers.py` and `tests/test_metrics_sync.py` exercise
the connector and the sync job entirely against these, monkeypatching the
one HTTP seam (`InstagramProvider._get`). Once a real token exists, the
honest next step is recording a handful of real responses alongside these
fixtures and confirming the field names still match — not rewriting the
provider, if Meta hasn't changed the shape.
