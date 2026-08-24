# Brand Memory OS — Builder Fest MVP

## Original problem statement
Build a web app for an agency lifecycle/email marketer to create a campaign brief and receive brand-safe, evidence-backed recommendations from a private library of past campaigns. The MVP must demonstrate one reliable end-to-end workflow: onboarding → brand memory → brief → semantic retrieval → cited recommendation → deterministic rule validation → blueprint → outcome recording.

## Architecture decisions
- React frontend, FastAPI backend, MongoDB.
- **Email + password auth** with bcrypt-hashed passwords, opaque hashed server-side sessions in MongoDB, CSRF header for every authenticated mutation.
- **Real tenant isolation** via `organization_members` scoping — no hardcoded workspace ID.
- **Real semantic retrieval** with `sentence-transformers/all-MiniLM-L6-v2` embeddings + application-side cosine ranking; no substring matching.
- **Real LLM analysis** using OpenAI (extraction + rationale, model `gpt-5-mini`). Falls back to honest 503 if `OPENAI_API_KEY` unavailable — deterministic parts still work.
- **Controlled brand research** with the OpenAI Agents SDK (Director → Evidence → Strategy → Safety/Synthesis). SSRF-guarded website fetch, prompt-injection checks, source citations, and a **human approval gate** before any policy is applied.
- **Deterministic hard-rule validator** independent of any LLM; runs after retrieval and before export; blocks blueprint download on prohibited-claim hit.
- **Object storage** via Emergent's integration proxy with a **local disk fallback** for dev.
- **Redis-backed rate limiter** with an in-process fallback.
- **Immutable guideline versions** — every change writes a new version.
- Public **`/demo`** route exposes the seeded Northstar workspace **read-only**; writes are refused at the API.

## User persona
Alex Morgan, an agency lifecycle marketer who needs fast, defensible campaign direction without losing brand context or misattributing performance.

## Core requirements (static)
Auth, seeded demo, onboarding (org → brand → research → guardrails → memory), campaign upload + paste from Klaviyo/Mailchimp/Figma/HubSpot/Iterable, semantic retrieval, evidence cards with citation, deterministic hard-rule enforcement, blueprint export blocked by rules, outcome recording, closed-loop memory update.

## Implemented
- 2026-04-01: Initial polished single-file MVP with seeded workspace, deterministic ranking, hard-rule check, export, outcome recording.
- 2026-04-02: Malformed brand-rule 500 → 422 hardening.
- 2026-08-22: Full rebuild to real vertical slice — server-generated org/brand IDs, cookie-signed session tenancy, real embeddings via sentence-transformers, real LLM extraction via GPT-5.4, connect-from-provider paste flow.
- 2026-08-24: Integrated hardened update — real bcrypt auth + CSRF, brand-research agent chain (OpenAI Agents SDK with SSRF guards and human approval gate), demo route locked read-only at the API, Redis rate limiter with in-process fallback, local storage fallback for dev.

## Backlog
- P0: `OPENAI_API_KEY` provisioning for the hosted preview so extraction/rationale/research run end-to-end (currently falls back to honest empty summaries).
- P1: Native OAuth sync for Klaviyo/Mailchimp/HubSpot/Iterable (paste path works today).
- P1: Second seeded organization + workspace switcher.
- P1: PDF blueprint export alongside Markdown.
- P2: Cross-instance Redis in production; multi-user roles inside an organization; audit exports.
