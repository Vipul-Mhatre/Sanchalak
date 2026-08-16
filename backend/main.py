"""
FlytBase Knowledge Agent — FastAPI Backend
Main application entry point.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ingestion import build_index, reindex_delta, search_customer_data, CHROMA_DIR
from docs_fetcher import fetch_docs, DocPassage
from llm import route_and_synthesize, check_contradictions

load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FlytBase Knowledge Agent",
    description="Conversational knowledge agent combining customer data and live docs",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Usage tracking (simple local store)
# ---------------------------------------------------------------------------

USAGE_LOG_FILE = Path(__file__).resolve().parent / "usage_log.json"


def _load_usage_log() -> list[dict]:
    if USAGE_LOG_FILE.exists():
        try:
            return json.loads(USAGE_LOG_FILE.read_text())
        except Exception:
            return []
    return []


def _save_usage_log(log: list[dict]):
    USAGE_LOG_FILE.write_text(json.dumps(log, indent=2, default=str))


def _log_query(question: str, sources: list[str], answer_length: int):
    log = _load_usage_log()
    log.append({
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "sources": sources,
        "answer_length": answer_length,
    })
    # Keep last 500 entries
    if len(log) > 500:
        log = log[-500:]
    _save_usage_log(log)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str


class Citation(BaseModel):
    id: str
    type: str  # "customer_data" or "docs"
    record_type: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    content_preview: str = ""
    source_site: Optional[str] = None


class Contradiction(BaseModel):
    analysis: str
    feature_request_id: Optional[str] = None
    title: Optional[str] = None
    requesting_accounts: list = []
    doc_url: Optional[str] = None
    explanation: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources_used: list[str]
    citations: list[Citation]
    contradictions: list[Contradiction]


class ReindexResponse(BaseModel):
    status: str
    changed_files: list[str] = []
    deleted_files: list[str] = []
    records_updated: int = 0
    records_deleted: int = 0


class UsageEntry(BaseModel):
    timestamp: str
    question: str
    sources: list[str]
    answer_length: int


class UsageResponse(BaseModel):
    total_queries: int
    recent_queries: list[UsageEntry]
    most_asked: list[dict]
    source_breakdown: dict


# ---------------------------------------------------------------------------
# Startup: build index if needed
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_build_index():
    """Build the ChromaDB index on startup if it doesn't exist."""
    chroma_path = Path(CHROMA_DIR)
    if not chroma_path.exists() or not any(chroma_path.iterdir()):
        print("[startup] Building initial ChromaDB index...")
        stats = build_index()
        print(f"[startup] Index built: {stats}")
    else:
        print("[startup] ChromaDB index already exists, skipping build.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY")),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint.
    Routes the question to appropriate tools, synthesizes a cited answer.
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Define the tool functions the LLM can call
    async def _search_customer(
        query: str,
        record_type: Optional[str] = None,
        account_name: Optional[str] = None,
        industry: Optional[str] = None,
        n_results: int = 10,
    ) -> list[dict]:
        return search_customer_data(
            query=query,
            n_results=n_results,
            record_type=record_type,
            account_name=account_name,
            industry=industry,
        )

    async def _fetch_docs_tool(query: str) -> list[DocPassage]:
        return await fetch_docs(query)

    try:
        result = await route_and_synthesize(
            question=question,
            search_fn=_search_customer,
            docs_fn=_fetch_docs_tool,
        )

        # Run contradiction check if both sources were used
        contradictions = []
        if "customer_data" in result["sources_used"] and "docs" in result["sources_used"]:
            # Get feature request results for contradiction check
            fr_results = search_customer_data(
                query=question,
                n_results=10,
                record_type="feature_request",
            )
            if fr_results:
                # Build a docs query from the top feature-request titles so the
                # check actually lands on the pages describing those features
                import re as _re
                fr_titles = []
                for r in fr_results[:5]:
                    title = r.get("content", "").split("\n")[0] if r.get("content") else ""
                    title = title.replace("Feature Request:", "").strip()
                    title = _re.sub(r"\(ID:\s*FR-\d+\)", "", title).strip()
                    if title:
                        fr_titles.append(title[:100])
                docs_query = " ".join(fr_titles[:3]) if fr_titles else question
                print(f"[chat] Contradiction docs query: {docs_query[:200]}")
                docs_passages = await fetch_docs(docs_query)
                contradiction_findings = await check_contradictions(
                    fr_results, docs_passages
                )
                contradictions = [
                    Contradiction(**c)
                    for c in contradiction_findings
                ]

        # Log usage
        _log_query(question, result["sources_used"], len(result["answer"]))

        return ChatResponse(
            answer=result["answer"],
            sources_used=result["sources_used"],
            citations=[Citation(**c) for c in result["citations"]],
            contradictions=contradictions,
        )

    except ValueError as e:
        if "GEMINI_API_KEY" in str(e):
            raise HTTPException(
                status_code=500,
                detail="Gemini API key not configured. Set GEMINI_API_KEY in backend/.env",
            )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"[chat] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/reindex", response_model=ReindexResponse)
async def reindex():
    """
    Trigger incremental delta reindex of the customer data corpus.
    Only re-embeds files that changed since last index.
    """
    try:
        result = reindex_delta()
        return ReindexResponse(**result)
    except Exception as e:
        print(f"[reindex] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Reindex error: {str(e)}")


@app.post("/api/full-reindex")
async def full_reindex():
    """Force a full rebuild of the index."""
    try:
        stats = build_index()
        return {"status": "rebuilt", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/usage", response_model=UsageResponse)
async def usage_stats():
    """Get usage statistics."""
    log = _load_usage_log()

    # Source breakdown
    source_counts = {}
    for entry in log:
        for src in entry.get("sources", []):
            source_counts[src] = source_counts.get(src, 0) + 1

    # Most asked questions (simple frequency by exact match)
    question_counts = {}
    for entry in log:
        q = entry.get("question", "").lower().strip()
        question_counts[q] = question_counts.get(q, 0) + 1

    most_asked = sorted(
        [{"question": q, "count": c} for q, c in question_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    recent = [UsageEntry(**e) for e in log[-20:]]
    recent.reverse()

    return UsageResponse(
        total_queries=len(log),
        recent_queries=recent,
        most_asked=most_asked,
        source_breakdown=source_counts,
    )


# ---------------------------------------------------------------------------
# Run with: uvicorn main:app --reload --port 8000
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
