# Brand Memory OS — Builder Fest MVP

## Original problem statement
Build a web app for an agency lifecycle/email marketer to create a campaign brief and receive brand-safe, evidence-backed recommendations from a private library of past campaigns. The MVP must demonstrate one reliable end-to-end workflow: onboarding → brand memory → brief → semantic retrieval → cited recommendation → deterministic rule validation → blueprint → outcome recording.

## Architecture decisions
- React frontend, FastAPI backend, MongoDB, hosted on Emergent.
- **Email + password auth** with bcrypt-hashed passwords, opaque hashed server-side sessions in MongoDB, CSRF header for every authenticated mutation.
- **Real tenant isolation** via `organization_members` scoping — no hardcoded workspace ID.
- **Real semantic retrieval** with `sentence-transformers/all-MiniLM-L6-v2` embeddings + application-side cosine ranking; no substring matching.
- **Real LLM analysis** using OpenAI or Emergent's `EMERGENT_LLM_KEY` proxy (extraction + rationale). Falls back to honest 503 if neither key is available — deterministic parts still work.
- **Controlled brand research** with the OpenAI Agents SDK (Director → Evidence → Strategy → Safety/Synthesis) and a Chat Completions fallback for Emergent-hosted previews. SSRF-guarded website fetch, prompt-injection checks, source citations, and a **human approval gate** before any policy is applied.
- **Deterministic hard-rule validator** independent of any LLM; runs after retrieval and before export; blocks blueprint download on prohibited-claim hit.
- **Native Klaviyo / Mailchimp sync** with Fernet-encrypted keys at rest, plus paste from Figma / HubSpot / Iterable.
- **Object storage** via Emergent's integration proxy with a **local disk fallback** for dev.
- **Redis-backed rate limiter** with an in-process fallback.
- **Immutable guideline versions** — every change writes a new version.
- Public **`/demo`** route exposes the seeded Northstar workspace **read-only**, including a seeded sample recommendation and a GET blueprint so judges can walk the full loop.

## User persona
Alex Morgan, an agency lifecycle marketer who needs fast, defensible campaign direction without losing brand context or misattributing performance.

## Core requirements (static)
Auth, seeded demo, onboarding (org → brand → research → guardrails → memory), campaign upload + paste from Klaviyo/Mailchimp/Figma/HubSpot/Iterable, native Klaviyo/Mailchimp sync, semantic retrieval, evidence cards with citation, deterministic hard-rule enforcement, blueprint export blocked by rules, outcome recording, closed-loop memory update.

## Implemented
- 2026-04-01: Initial polished single-file MVP with seeded workspace, deterministic ranking, hard-rule check, export, outcome recording.
- 2026-04-02: Malformed brand-rule 500 → 422 hardening.
- 2026-08-22: Full rebuild to real vertical slice — server-generated org/brand IDs, cookie-signed session tenancy, real embeddings via sentence-transformers, real LLM extraction, connect-from-provider paste flow.
- 2026-08-24: Integrated hardened update — real bcrypt auth + CSRF, brand-research agent chain (OpenAI Agents SDK with SSRF guards and human approval gate), demo route locked read-only at the API, Redis rate limiter with in-process fallback, local storage fallback for dev.
- 2026-08-26: Design-structure release. Campaign intake reduced to **name / title / description** — objective, audience, offer, and category are derived from the description (LLM with a deterministic rules fallback). New `services/email_structure.py` parses email HTML into an ordered module sequence with a fixed vocabulary, entirely rule-based. Campaigns now store `modules`, `module_signature`, `module_source`, and `category`. Retrieval reweighted to 0.55 semantic / 0.12 objective / 0.08 audience / 0.08 evidence quality / **0.10 layout similarity** / **0.07 category**. Recommendations carry `recommended_structure`, a consensus layout assembled only from blocks the brand has actually sent, each citing its source campaigns. Blueprint exports the structure spec; refuses honestly when no layout can be grounded.
- 2026-08-26: Retrieval + UX fixes found by end-to-end testing against a running stack.
  - **Retrieval returned zero evidence for obviously relevant campaigns.** Briefs are intent-language; the no-LLM ingestion fallback stored raw email copy. Measured 0.2657 similarity against a 0.35 threshold. Added `summarize_for_retrieval` to restate each email as intent (0.378 after; unrelated controls ≤0.15) and lowered the threshold to 0.30 with the measurements recorded in-code.
  - **Demo diverged from reality.** Seeds were hand-written summaries, so the demo passed while real uploads failed. Demo campaigns are now real HTML run through the production parser.
  - Reseeding through the real parser immediately exposed two parser bugs: CTA blocks were absorbed into the preceding block (buttons now start their own module), and "no discount mechanics" was misread as a promo banner (offer detection now requires a concrete offer signal and honours negation).
  - Unified `process_campaign` / `process_pasted` into one `analyze_campaign` path — they were ~90% duplicated.
  - Frontend polled a 404 brand endpoint forever; polling now stops on terminal errors and once nothing is processing, with a proper "brand no longer exists" screen.
  - UX: plain-language recommendation summary, "Build this, top to bottom" structure panel with a Copy structure action, and an actionable empty state with two concrete fixes.
  - Blank audience is now stored blank rather than as invented boilerplate.
- 2026-08-24: Emergent hackathon pass — Emergent LLM proxy fallback, native Klaviyo/Mailchimp UI, seeded demo recommendation + read-only blueprint, dashboard counts/org identity, CORS DELETE, Chat Completions extraction.

## Backlog
- P0: Confirm hosted preview has `EMERGENT_LLM_KEY` or `OPENAI_API_KEY` so extraction/rationale/research run live.
- P1: Native OAuth (instead of API keys) for Klaviyo/Mailchimp and HubSpot/Iterable.
- P1: Second seeded organization + workspace switcher.
- P1: PDF blueprint export alongside Markdown.
- P2: Cross-instance Redis in production; multi-user roles inside an organization; audit exports.
