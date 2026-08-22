# Brand Memory OS — Builder Fest MVP

## Original problem statement
Build a web app for an agency lifecycle/email marketer to create a campaign brief and receive brand-safe, evidence-backed recommendations from a private library of past campaigns. The MVP must demonstrate one reliable seeded-workspace workflow: brief, retrieval, evidence, deterministic brand-rule validation, export, and outcome recording.

## Architecture decisions
- React frontend with FastAPI backend and MongoDB persistence.
- One seeded Northstar Coffee Co. workspace; all records are scoped to the workspace ID.
- Deterministic hybrid-style structured matching for the demo, with explicit campaign evidence and attached outcomes.
- Hard-rule validation is independent from recommendation ranking and blocks prohibited claims before export.
- Markdown blueprint download keeps output readable and dependable.
- Browser localStorage provides brief autosave for the demo.

## User persona
Alex Morgan, an agency lifecycle marketer who needs fast, defensible campaign direction without losing brand context or misattributing performance.

## Core requirements (static)
Seeded demo access, brand rules and tokens, campaign library, explicit metrics, brief validation/autosave, ranked recommendations, evidence cards, hard-rule conflicts, incomplete/no-evidence states, blueprint export, outcome recording, and closed-loop memory.

## Implemented
- 2026-04-01: Replaced starter template with a polished Brand Memory OS workspace and one-click demo entry.
- 2026-04-01: Added seeded workspace, rules, three campaign records, outcomes, recommendations, hard-rule validation, blueprint download, rules editing, library view, and outcome recording APIs.
- 2026-04-01: Added responsive UI with evidence-backed recommendation cards, incomplete metrics labels, blocked conflict states, empty evidence state, and browser draft autosave.
- 2026-04-01: Verified API seed, recommendation matching/no-evidence behavior, browser flow, responsive layout, export, memory editing, and outcome flow.
- 2026-04-02: Hardened `PUT /api/rules` with a `Rules` Pydantic model — malformed payloads now return HTTP 422 with field-level detail instead of 500; valid persistence unchanged.
- 2026-04-02: Regression verified end-to-end via curl (no-evidence=0 recs, matching=3 recs, blueprint blocked=409 on prohibited claim, outcome recording closes the loop) and Playwright confirmed landing → workspace → empty-state → matching-cards selectors.

## Prioritized backlog
- P0: Add a managed private object-storage path for real campaign preview uploads.
- P1: Add a model-powered explanation layer behind the existing deterministic evidence contract.
- P1: Add a second demo workspace and explicit workspace switcher test path.
- P2: Add PDF export alongside Markdown.
- P2: Add campaign ingestion form for structured records.

## P0/P1/P2 remaining tasks
- P0: Production-grade signed asset URLs and upload failure UI.
- P1: Optional LLM explanation enrichment with graceful fallback.
- P1: Stronger workspace identity and isolation tests.
- P2: PDF blueprint rendering and richer visual email previews.
