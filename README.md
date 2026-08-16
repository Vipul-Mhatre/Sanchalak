# Sanchalak: A Cross-Source Knowledge Agent for FlytBase Solutions Engineering

A conversational knowledge agent that answers questions by combining:
1. **Local customer-data corpus** (accounts, issues, feature requests, tasks, meeting notes)
2. **Live FlytBase docs** — fetched at query time from docs.flytbase.com and releases.flytbase.com

## Hard Requirements (Non-Negotiable)

| # | Requirement |
|---|-------------|
| 1 | Answer questions from the local customer-data corpus |
| 2 | Answer questions from live docs — fetched at query time, never pre-scraped |
| 3 | Combine both sources in a single answer when needed |
| 4 | Ground every claim in a specific record ID or doc URL/section |
| 5 | Reflect corpus updates via incremental/delta reindexing |

---

## Quick Start

```bash
# 1. Install backend dependencies
cd backend
python -m venv .venv          # required on WSL/Linux (PEP 668)
source .venv/bin/activate     # WSL/Linux — or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# 2. Set up API keys
cp .env.example .env
# Edit .env — add GEMINI_API_KEY and/or GROK_API_KEY

# 3. Install frontend dependencies
cd ../frontend
npm install

# 4. Start both servers
# Terminal 1:
cd backend && .venv/bin/python -m uvicorn main:app --port 8000

# Terminal 2:
cd frontend && npm run dev
```

The app will be available at `http://localhost:5173` (frontend) and `http://localhost:8000` (backend).

## LLM Fallback Chain (works without any API key)

The agent never breaks if an API key is missing or invalid. It falls back in this order:

1. **Gemini** (`GEMINI_API_KEY`) — primary LLM, tries `gemini-2.5-flash` then `gemini-2.0-flash`
2. **Groq** (`GROK_API_KEY`, e.g. `gsk_...`) — OpenAI-compatible LLaMA model, `llama-3.3-70b-versatile`
3. **Local synthesis** — no LLM needed: formats the retrieved records directly with citations

The pipeline always retrieves both sources first (customer data + live docs), then asks the LLM to synthesize. If every LLM fails, it still returns a grounded answer from the search results. Contradiction checks follow the same fallback chain.

---

## Project Structure

```
flytgtm/
├── backend/          # FastAPI application
│   ├── main.py        # Routes, chat endpoint, reindex, usage tracking
│   ├── ingestion.py   # Parsers, ChromaDB index, delta reindex
│   ├── docs_fetcher.py # Live GitBook search + page fetch with cache
│   ├── llm.py         # Gemini Flash tool-calling + citation enforcement
│   ├── requirements.txt
│   └── .env.example
├── frontend/         # React + Vite chat UI
│   ├── src/App.jsx    # Chat interface with citation chips & reindex panel
│   ├── src/App.css    # Dark-mode styling
│   └── package.json
├── dataset/          # Customer-data corpus (5 Markdown files)
│   ├── accounts.md       | 51 accounts
│   ├── feature_requests.md | 56 feature requests
│   ├── issues.md         | ~700+ issues
│   ├── meeting_notes.md  | ~200+ meeting notes
│   └── tasks.md          | ~400+ tasks
├── chroma_db/        # Persistent ChromaDB vector store (created at runtime)
└── README.md          # This file
```

---

## Backend Details

### Running the Backend Only

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The backend runs on `http://localhost:8000` and provides these endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check, verifies Gemini API key |
| `/api/chat` | POST | Main chat — routes question, retrieves from both sources, synthesizes cited answer |
| `/api/reindex` | POST | Incremental delta reindex of changed customer-data records |
| `/api/full-reindex` | POST | Force a full rebuild of the ChromaDB index |
| `/api/usage` | GET | Usage statistics: total queries, source breakdown, most-asked questions |

### Dataset Format

All 5 data files in `/dataset` are **Markdown with pipe-delimited tables**, except meeting notes which use heading-based sections:

| File | Records | Format |
|---|---|---|
| `accounts.md` | 51 accounts | Pipe table with columns: ID, Name, Industry, Region, Tier, Health, ARR, Owner, Devices |
| `feature_requests.md` | 56 feature requests | Pipe table; **no explicit IDs** — synthetic `FR-0001`…`FR-0056` assigned from row order |
| `issues.md` | ~700+ issues | Pipe table |
| `tasks.md` | ~400+ tasks | Pipe table |
| `meeting_notes.md` | ~200+ notes | `## MTG-NNNN: Account Name` headings with `**Topic:**`, `**Attendees:**`, `**Date:**`, `**Action Items:**` fields |

**Key parsing notes:**
- Feature request accounts field uses `&` for "and" (e.g. "Silver Creek Oil & Gas") — handled in parsing
- Feature requests cross-reference account names (not IDs) — name-to-ID lookup is built in
- Dates are ISO format (`2026-MM-DD`) — consistent, no parsing issues

### Delta Reindex

The `reindex_delta()` function (called via `/api/reindex`) incrementally re-embeds only changed/added records and removes deleted ones. It uses a hash file (`backend/file_hashes.json`) to detect changes.

To demo delta reindexing:
1. Edit a record in any `/dataset/*.md` file
2. Call `POST /api/reindex`
3. Re-ask the same question — the update should be reflected

To force a full rebuild: `POST /api/full-reindex`

### Citation Enforcement

The synthesis prompt (`llm.py:ROUTER_SYSTEM_PROMPT`) enforces:
- Every factual claim **must** cite its source (record ID or doc URL)
- If insufficient information: say "I don't have enough information to answer this question"
- No fabrication or guessing — only state what is directly supported

---

## Frontend Details

### Running the Frontend Only

```bash
cd frontend
npm run dev
```

The frontend runs on `http://localhost:5173` (Vite dev server).

The chat UI features:
- Citation chips with source badges (`📊 Customer Data`, `📄 Live Docs`, or `📊 Customer Data + 📄 Live Docs`)
- Source badges showing which corpus(s) the answer came from
- Expandable citation details with copyable URLs
- Contradiction flags when customer data says "requested" but docs say "shipped"
- Reindex panel for running delta reindex
- Usage stats panel with query frequency and source breakdown
- Example query buttons for quick demos

---

## API Endpoints Reference

### `POST /api/chat`

```json
{ "question": "Your question here" }
```

Returns:
```json
{
  "answer": "The synthesized answer with inline citations",
  "sources_used": ["customer_data", "docs"],  // or one of them
  "citations": [
    { "id": "acct-001", "type": "customer_data", "record_type": "account", "content_preview": "..." },
    { "id": "https://docs.flytbase.com/...", "type": "docs", "title": "...", "content_preview": "..." }
  ],
  "contradictions": [ { "analysis": "..." } ]  // optional, if both sources used
}
```

### `POST /api/reindex`

Triggers incremental delta reindex. Returns `ReindexResponse` with `records_updated`, `records_deleted`, and `changed_files`.

### `GET /api/health`

Returns status including whether `GEMINI_API_KEY` is set.

### `GET /api/usage`

Returns usage statistics including total queries, source breakdown, most-asked questions, and recent query log.

---

## Demo Script (from CLAUDE.md)

1. **Core flow**: Ask "What are the open issues for Meridian AgriTech?" → answer from customer data
2. **Docs flow**: Ask "How does mission scheduling work in FlytBase?" → answer from live docs
3. **Combined flow**: Ask "Which accounts requested a feature that the platform already supports according to the docs?" → should identify accounts with feature requests AND show the feature exists in docs
4. **Citation test**: Ask "What is the weather on Mars?" → model should explicitly say it doesn't have enough information
5. **Delta reindex**: Edit a record in `/dataset/`, call `/api/reindex`, re-ask → update reflected

---

## Requirements

- **Python 3.11+** for the backend
- **Node.js 20+** and **npm** for the frontend
- **Google Gemini API key** (set in `backend/.env`)
- **httpx**, **beautifulsoup4**, **chromadb**, **sentence-transformers**, **google-genai**, **fastapi**, **uvicorn**

---

## Development Notes

- **No agent framework** — fixed pipeline: classify → retrieve → synthesize
- **Vector store**: chromadb local/embedded, `all-MiniLM-L6-v2` embeddings
- **Docs retrieval**: live fetch at query time via GitBook `/~gitbook/site-index` JSON endpoint
- **Cache**: short-lived (5 min) in-memory fallback only if live fetch fails — never pre-scraped
- **Delta reindex**: must be incremental, not a full rebuild disguised as one
- **Contradiction flag**: highest-priority bonus feature — customer data "requested" + docs "shipped"