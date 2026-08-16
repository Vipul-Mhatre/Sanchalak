# CLAUDE.md — Project Context

Persistent context for this repo. Read this before making changes. Update it whenever a decision, gotcha, or data-format detail is discovered — don't let this go stale.

## What we're building

A conversational knowledge agent (PS2: "Knowledge Base Over Customer Data") that answers questions by combining:
1. A local synthetic customer-data corpus (accounts, issues, feature requests, tasks, meeting notes)
2. Live public FlytBase docs — docs.flytbase.com and releases.flytbase.com

This is a hackathon MVP. Prioritize a working end-to-end flow over polish. Do not skip any of the 5 hard requirements below — they are judged explicitly.

## Hard requirements (non-negotiable)

1. Answer questions from the local customer-data corpus.
2. Answer questions from live docs — fetched at query time, never pre-scraped into a static copy.
3. Combine both sources in a single answer when a question needs it. Canonical test: "Which accounts requested a feature the platform already supports according to the docs?"
4. Ground every claim in a specific record ID or doc URL/section. If there isn't enough information, say so explicitly rather than guessing.
5. Reflect corpus updates (added/changed/removed records) without a full manual rebuild — incremental/delta reindexing only.

## Data

- Customer-data folder path: `/dataset`
- Format: **Markdown with pipe-delimited tables** (all 5 files). Meeting notes use heading-based sections (`## MTG-NNNN`) instead of tables.
- Record types present: accounts (51), issues (~700+), feature requests (56), tasks (~400+), meeting notes (~200+)
- Key metadata fields to tag on ingestion: record type, account name, industry, plan tier (if present), date, category
- **Quirks found:**
  - Feature requests have **no explicit ID column** — synthetic `FR-0001`…`FR-0056` assigned from row order
  - Meeting notes use `## MTG-NNNN: Account Name` headings with `**Topic:**`, `**Attendees:**`, `**Date:**`, `**Action Items:**` fields — not table format
  - Feature requests cross-reference account names (not IDs) — need name-to-ID lookup
  - Dates are ISO format (`2026-MM-DD`) — consistent, no parsing issues
  - Both docs sites are **GitBook-powered** with `/~gitbook/site-index` JSON endpoint for search

## Architecture decisions (locked in — don't relitigate)

- **No agent framework / harness.** This is a fixed pipeline (classify → retrieve → synthesize), not an open-ended agent loop. Use direct Anthropic API tool-use: give the model `search_customer_data(query)` and `fetch_docs(query)` as tools and let it call what it needs in one request cycle. Do not introduce LangChain/AutoGPT-style orchestration — it adds complexity with no payoff here.
- **Vector store:** chromadb, local/embedded, no external service dependency.
- **Docs retrieval:** live fetch at query time (search-then-fetch or direct page fetch), with a short-lived cache as a fallback only if the live fetch fails. Never show a raw fetch error in the demo — degrade gracefully with a "using cached data, may be slightly stale" message.
- **Citation enforcement:** synthesis prompt must enforce "cite or refuse" — every claim gets a record ID or doc URL, or the model states it doesn't have enough information. This is tested live in the demo with a deliberately unanswerable question — don't weaken this rule for the sake of fuller-sounding answers.
- **Delta reindexing:** `reindex_delta(changed_ids)` re-embeds only changed/added records and removes deleted ones. This is demoed live (edit a record, re-ask, show it reflected) — it must actually be incremental, not a full rebuild disguised as one.

## Build order

1. Inspect and parse the customer-data folder; confirm format before writing ingestion code.
2. Ingestion pipeline: parse → chunk → embed → store in chromadb with metadata.
3. Live-docs fetch tool; test against 2–3 real queries.
4. Query router (source classification: customer / docs / both).
5. Synthesis step with citation enforcement; test that unsupported claims get refused.
6. Delta reindex function; test by editing one record.
7. Chat UI wiring; confirm full core flow (requirements 1–5) end to end.
8. Bonus features, in priority order, only if time remains:
   - Contradiction flag (customer data says "requested," docs say "shipped") — highest priority, this is the standout feature
   - Natural-language querying across category/time/industry (aggregate questions over metadata, not just semantic search)
   - Usage-signal tracking (log questions asked, surface "most-asked")
   - Ambiguous/multi-part question decomposition (split into sub-queries, re-synthesize)
9. Rehearse the demo script (see DEMO_SCRIPT.md).

## Tech stack

- Language/framework: **Python 3 + FastAPI** (backend), **React + Vite** (frontend)
- Vector store: chromadb (local, embedded, `all-MiniLM-L6-v2` for embeddings via sentence-transformers)
- LLM: **Gemini 2.0 Flash** (Google GenAI SDK), tool-use for `search_customer_data` and `fetch_docs`
- Frontend: React chat UI with citation chips, source badges, reindex panel, usage stats

## Gotchas / decisions log

Add entries here as you hit them — this is the section that saves the most time on re-runs.

- GitBook site-index returns ALL pages in one JSON blob — good for search, but need to keyword-filter before fetching full pages
- `create-vite` template on Windows can mangle paths with spaces — use `cd` + `.` pattern instead of passing full path
- sentence-transformers pulls in PyTorch (~2GB) — takes time on first `pip install`
- ChromaDB persistent client needs an absolute path string, not Path object on some versions
- Feature request accounts field uses `&` for "and" in some names (e.g. "Silver Creek Oil & Gas") — must handle in parsing
- WSL/Ubuntu's Python is PEP 668 externally-managed — must use a venv (`python3 -m venv .venv`), never system pip
- `uvicorn --reload` on Windows spawns a subprocess with the system Python (breaks venv imports) — use `python -m uvicorn` without `--reload`
- Gemini models `gemini-2.0-flash` are retired (404) — model list fallback in `_call_gemini` (2.5-flash → 2.0-flash-001 → 2.0-flash), and it must degrade gracefully
- `gsk_` prefixed keys are Groq (api.groq.com, OpenAI-compatible), NOT x.ai Grok — fallback LLM uses Groq `llama-3.3-70b-versatile`
- LLM fallback chain: Gemini → Groq → local synthesis (no API needed); pipeline retrieves both sources up-front so local synthesis always has grounded data
- Feature request titles in Chroma contain `(ID: FR-xxxx)` — strip with regex before using as docs-search query terms; stopword-filter docs search terms or generic pages outrank the real ones

## What NOT to do

- Don't scrape/cache the full docs sites ahead of time — must be live fetch at query time.
- Don't build a general-purpose agent loop for this — the flow is fixed and small.
- Don't let the synthesis step produce uncited claims, even to make demo answers sound more complete.
- Don't sacrifice the 5 hard requirements for bonus features — bonuses are worthless if the core flow breaks.
