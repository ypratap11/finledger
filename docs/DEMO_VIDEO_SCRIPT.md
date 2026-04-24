# FinLedger — 90s Demo Script

**Length target:** 90 seconds. ~200 words spoken at a brisk-but-natural 145-160 wpm.
**Audience:** founders / engineers / finance — threaded together, no jargon stacks.
**Tone:** confident, factual, one verb per beat. No hype words ("revolutionary", "powerful", "seamless").

Each beat: `[seconds — UI / camera direction] "spoken line"`. Pause briefly between paragraphs for breathing room and screen-cut latency.

---

### Beat 1 — Hook (0:00 – 0:08)
**[UI: GitHub repo page, then cut to terminal with cursor blinking]**

> "Every SaaS company rebuilds the same broken pipeline: webhook in, maybe a ledger, maybe reconciliation, finance crying at month-end. FinLedger is the open-source one you don't have to build."

### Beat 2 — One-command bring-up (0:08 – 0:18)
**[UI: `docker compose up` running, then browser opening to `http://localhost:8003`]**

> "One `docker compose up`. Forty seconds later, you have a working ledger, a recognition engine, and an admin UI — already populated."

### Beat 3 — Source events + ledger integrity (0:18 – 0:33)
**[UI: `/` inbox page showing source events list, then `/journal` showing the journal entries, zoom on the debit/credit columns]**

> "Stripe charges, Zuora invoices — they land here. Every event hash-chained, so tampering breaks the chain. Every journal entry posted with `debits = credits` enforced by Postgres itself, not application code."

### Beat 4 — All four ASC 606 patterns (0:33 – 0:53)
**[UI: `/revrec/contracts` showing the 5 seed cards, hover Umbrella (consumption), click into Soylent (PAYG)]**

> "Revenue recognition handles all four ASC 606 Step 5 patterns out of the box: ratable subscriptions, point-in-time licenses, prepaid usage commitments, and pay-as-you-go. Same engine. One balanced journal entry per run."

### Beat 5 — Live event flow (0:53 – 1:08)
**[UI: split — terminal running `curl POST /revrec/usage`, then `/revrec/usage` page refresh showing the new event, then `/revrec` waterfall updating]**

> "A usage event arrives. Revenue accrues to Unbilled AR. The waterfall projects the next twelve months. Your CFO sees backlog, deferred revenue, and unbilled receivables in one place."

### Beat 6 — Recon + audit story (1:08 – 1:22)
**[UI: split — `/recon` page with matched/unmatched breaks on left, terminal showing trial balance SQL returning equal debits and credits on right]**

> "Books always balance. Hash chain always intact. Stripe and Zuora reconcile against the same ledger. CSV export today, ERP connectors next."

### Beat 7 — Call to action (1:22 – 1:30)
**[UI: full-screen GitHub URL, repo stars/fork buttons visible]**

> "It's open source. **github.com/ypratap11/finledger**. Take it, run it, ship faster."

---

## Delivery notes

- **Pace per beat:** Beats 1, 2, 7 land slightly slower (people remember openings and endings). Beats 3-6 brisk.
- **Emphasis words** (lean in): *open-source*, *forty seconds*, *hash-chained*, *Postgres itself*, *all four*, *pay-as-you-go*, *one balanced journal entry*, *always balance*, *open source*.
- **Avoid:** "we built", "I built" — keep it product-first. The repo URL doubles as your founder credit.
- **Cuts if you go over time** (in priority order to drop): the hash-chain mention in Beat 3, the "CSV export today, ERP connectors next" half of Beat 6.

## Visual capture checklist

Before recording:

- [ ] Run `docker compose -f docker-compose.full.yml down -v && up --build` so seed data is fresh
- [ ] Disable browser extensions (or use Incognito) so the address bar is clean
- [ ] Bump browser zoom to ~110-125% so the type is readable on YouTube/LinkedIn at small sizes
- [ ] Hide bookmarks bar; use a clean OS theme
- [ ] Set terminal font to ~16pt, dark theme, no clutter

Run order during recording:

1. GitHub repo (Beat 1)
2. Terminal: `docker compose up` truncated to ~4 seconds, jump to the browser at `localhost:8003` (Beat 2)
3. Click Inbox → Journal in the UI (Beat 3)
4. Click Revenue → Contracts → Soylent (Beat 4)
5. Switch to terminal, run a `curl POST /revrec/usage` against Soylent's obligation, switch back, F5 the usage page, then click Revenue waterfall (Beat 5)
6. Click Recon, then split-screen the terminal trial-balance query (Beat 6)
7. End on the GitHub URL (Beat 7)

## After recording

- Trim silence at start/end.
- Add a 1-second fade-in/fade-out on audio.
- Lower-third overlay at 0:00: "FinLedger — open-source SaaS finance pipeline".
- Lower-third at 1:22: the GitHub URL again.
- No background music for the LinkedIn cut (auto-plays muted; voice-only is more recognizable). Optional soft music for the YouTube cut.
- Caption the whole thing — most LinkedIn views are sound-off.

---

## A/B tests worth running later

If the first cut underperforms, the levers most likely to move it:

1. Open with the JE materializing (Beat 3 visual) instead of the GitHub repo. Show before tell.
2. Replace Beat 7 with a "watch a SaaS finance team install this in their repo" follow-up clip.
3. Drop the technical Postgres-trigger detail (Beat 3 second sentence) for a non-engineer cut.
