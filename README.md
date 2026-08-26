# Brand Memory OS

Builder Fest entry on Emergent. Brand Memory OS turns a brand's approved email history into cited campaign direction. It retrieves similar past campaigns, explains the match, enforces deterministic claim rules, and refuses to export when evidence or policy is insufficient.

## The loop, in three fields

Give a campaign a **name**, a **title**, and a **short description** of what you want. Everything else is derived:

1. **Read the description** — objective, audience, offer, and category are extracted from plain language. No LLM key? Deterministic rules fill them instead.
2. **Search this brand's memory** — semantic copy match, plus **layout similarity** and category match against past sends.
3. **Assemble the structure** — a block-by-block layout (`header > hero > testimonial > cta > footer`) built only from patterns this brand has already sent. Each block cites the campaigns it came from.
4. **Run the hard rules** — a prohibited claim blocks the export outright.

The deliverable is the **structure**, not a rendered design: a spec you build in Figma, Klaviyo, or any ESP. When the evidence has no readable layout, it says so rather than inventing one.

### Design-structure analysis

`backend/services/email_structure.py` parses email HTML into an ordered module sequence using a fixed vocabulary (header, hero, promo banner, text, image + copy, product grid, product card, social proof, CTA, social row, footer). It is entirely rule-based — no model call — so structure extraction is deterministic and works without any API key. Unreadable input returns an empty list, never a guess.

### Why retrieval normalizes both sides

A brief is written as intent ("introduce the winter roast to active subscribers"); an email is written as marketing copy. Embedding those directly compares two different registers, and cosine similarity collapses — a genuinely relevant past campaign scored **0.27 against a 0.35 threshold** and was silently discarded.

`summarize_for_retrieval` rewrites each email into the same register the brief uses, from its subject, hero heading, CTA, category, and layout. The same relevant campaign now scores **0.38**, while unrelated briefs stay at **0.15 and below**. The threshold sits at 0.30 — clear of both, so weak evidence is still refused.

The demo workspace is seeded as **real HTML through this same pipeline**, not as hand-written summaries. Whatever a visitor sees in the demo is what their own paste produces; the two cannot drift apart.

## What changed

- Three-field campaign intake (name / title / description) — objective, audience, and offer are derived, not typed
- Deterministic HTML → design-module extraction stored on every ingested campaign
- Retrieval ranks on layout similarity and brand category alongside copy semantics
- Blueprints export a cited, module-by-module structure instead of prose
- Email/password accounts with bcrypt-hashed passwords
- Opaque, hashed server-side sessions in MongoDB
- CSRF protection for every authenticated mutation
- Organization membership authorization and brand-level tenant isolation
- Public demo with an explicit read-only capability and a seeded sample recommendation
- Five-step onboarding: organization, brand, research, guardrails, memory
- Controlled OpenAI Agents SDK brand-research handoffs, with a Chat Completions fallback
- SSRF protection, bounded website fetches, prompt-injection checks, structured outputs, citations, and a human approval gate
- Direct OpenAI **or** Emergent `EMERGENT_LLM_KEY` for extraction, rationale, and research
- Native Klaviyo / Mailchimp API-key sync (encrypted at rest) plus paste from Figma / HubSpot / Iterable
- Local development storage fallback when the optional integration object store is unavailable
- Security headers, exact-origin CORS, Redis-distributed rate limits, upload limits, and immutable guideline versions

## Architecture

```text
React client
  ├─ secure session cookie + CSRF header
  └─ five-step onboarding / review UI
          │
FastAPI API
  ├─ auth + organization membership
  ├─ deterministic brand guardrails
  ├─ semantic campaign retrieval
  ├─ OpenAI / Emergent LLM extraction
  ├─ Klaviyo + Mailchimp import
  └─ Agents SDK research chain
       Director → Evidence → Strategy → Safety/Synthesis
          │
MongoDB (users, sessions, memberships, brands, versions, evidence)
Object storage integration or local development storage
```

Agent research never updates active policy automatically. A report is saved as `awaiting_review`; an authenticated owner must explicitly approve it, after which the API creates a new guideline version and records who approved it.

## Run locally

Requirements: Python 3.11+, Node 20+, MongoDB.

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
cd frontend
yarn install
yarn start
```

Set `OPENAI_API_KEY` **or** `EMERGENT_LLM_KEY` in `backend/.env` to enable brand research, extraction, and grounded rationale. Without either key, deterministic ingestion and guardrails remain available, and research returns an honest `503` instead of a fake result.

For production, set `COOKIE_SECURE=true`, `ENVIRONMENT=production`, an exact HTTPS `CORS_ORIGINS` value, durable object storage, a persistent MongoDB deployment, and `REDIS_URL` so security counters are shared across API instances. Without Redis the application intentionally falls back to a single-process limiter for local development.

## Tests

```bash
cd backend
pytest -q
python -m py_compile server.py security.py services/brand_research.py

cd ../frontend
yarn build
```

Set `TEST_API_URL=http://localhost:8000` to include deployed API smoke tests.

## Important controls

- Website research accepts only public HTTP(S) URLs and rejects local/private IP ranges.
- Website content is untrusted evidence, never agent instructions.
- Reports may cite only the approved, safely fetched source URL.
- Conflicting approved/prohibited claims cannot be applied.
- Prohibited claim matches block blueprint export independently of any model.
- Demo writes are rejected at the API even if the UI is bypassed.
- Provider API keys are encrypted at rest and never returned to the client.
- API keys never leave the backend environment.
