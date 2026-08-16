"""
LLM abstraction layer.
Uses Google Gemini Flash as primary, Grok as fallback, local synthesis as last resort.
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
import httpx

load_dotenv()

# ---------------------------------------------------------------------------
# Client setup
# ---------------------------------------------------------------------------

_gemini_client: Optional[genai.Client] = None
_grok_client: Optional[httpx.AsyncClient] = None


def _get_gemini_client() -> Optional[genai.Client]:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if api_key and api_key != "your_gemini_api_key_here":
            try:
                _gemini_client = genai.Client(api_key=api_key)
            except Exception:
                _gemini_client = None
    return _gemini_client


def _get_grok_client() -> Optional[httpx.AsyncClient]:
    """Groq API client (gsk_ keys) — OpenAI-compatible endpoint."""
    global _grok_client
    if _grok_client is None:
        api_key = os.getenv("GROK_API_KEY", "")
        if api_key:
            _grok_client = httpx.AsyncClient(
                base_url="https://api.groq.com/openai/v1",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
    return _grok_client


async def _call_gemini(messages: list, tools=None, system_instruction=None, temperature=0.1) -> Optional[str]:
    """Try Gemini, return None on failure."""
    client = _get_gemini_client()
    if not client:
        return None
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash-001", "gemini-2.0-flash"]
    for model in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[tools] if tools else None,
                temperature=temperature,
            )
            response = client.models.generate_content(
                model=model,
                contents=messages,
                config=config,
            )
            text = ""
            for part in response.candidates[0].content.parts:
                if part.text:
                    text += part.text
            if text:
                return text
        except Exception as e:
            print(f"[llm] Gemini model {model} failed: {e}")
    return None


async def _call_grok(messages: list, system_instruction=None, temperature=0.1) -> Optional[str]:
    """Try Groq (LLaMA) as fallback, return None on failure."""
    client = _get_grok_client()
    if not client:
        return None
    try:
        fallback_messages = []
        if system_instruction:
            fallback_messages.append({"role": "system", "content": system_instruction})
        for msg in messages:
            role = "user" if msg.role == "user" else "assistant"
            text = ""
            for part in msg.parts:
                if part.text:
                    text += part.text
                elif part.function_call:
                    text += f"[tool_call: {part.function_call.name}]"
                elif part.function_response:
                    text += f"[tool_response: {part.function_response.response}]"
            if text:
                fallback_messages.append({"role": role, "content": text})

        resp = await client.post("/chat/completions", json={
            "model": "llama-3.3-70b-versatile",
            "messages": fallback_messages,
            "temperature": temperature,
        })
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[llm] Groq failed: {e}")
        return None


def _local_synthesis(question: str, customer_data_results: list, docs_results: list, sources_used: set) -> dict:
    """Local fallback: format search results directly without LLM."""
    answer_parts = []
    citations = []
    
    if customer_data_results:
        answer_parts.append("**Customer Data Results:**\n")
        for r in customer_data_results[:5]:
            answer_parts.append(f"- [{r['id']}] {r['content'][:300]}...\n")
            citations.append({
                "id": r["id"],
                "type": "customer_data",
                "record_type": r.get("metadata", {}).get("record_type", ""),
                "content_preview": r["content"][:200],
            })
    
    if docs_results:
        answer_parts.append("\n**Documentation Results:**\n")
        for p in docs_results[:3]:
            answer_parts.append(f"- [{p.url}] {p.title}\n  {p.content[:300]}...\n")
            citations.append({
                "id": p.url,
                "type": "docs",
                "url": p.url,
                "title": p.title,
                "content_preview": p.content[:200],
                "source_site": p.source_site,
            })
    
    if not answer_parts:
        answer = "I don't have enough information to answer this question."
    else:
        answer = "".join(answer_parts)
        answer += "\n---\n*Answer generated from local search results (no LLM available).*"
    
    return {
        "answer": answer,
        "sources_used": list(sources_used),
        "citations": citations,
        "contradictions": [],
    }


# ---------------------------------------------------------------------------
# Tool definitions (schemas for search_customer_data and fetch_docs)
# ---------------------------------------------------------------------------

SEARCH_CUSTOMER_DATA_TOOL = types.FunctionDeclaration(
    name="search_customer_data",
    description=(
        "Search the local customer data corpus for relevant records. "
        "Use this when the question is about customer accounts, support issues, "
        "feature requests, tasks, or meeting notes. "
        "Returns matching records with IDs and metadata."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "query": types.Schema(
                type="STRING",
                description="The search query to find relevant customer data records.",
            ),
            "record_type": types.Schema(
                type="STRING",
                description=(
                    "Optional filter by record type. "
                    "One of: account, feature_request, issue, task, meeting_note"
                ),
            ),
            "account_name": types.Schema(
                type="STRING",
                description="Optional filter by exact account name.",
            ),
            "industry": types.Schema(
                type="STRING",
                description="Optional filter by industry.",
            ),
        },
        required=["query"],
    ),
)

FETCH_DOCS_TOOL = types.FunctionDeclaration(
    name="fetch_docs",
    description=(
        "Fetch relevant content from FlytBase's live public documentation "
        "(docs.flytbase.com and releases.flytbase.com). "
        "Use this when the question is about FlytBase platform features, capabilities, "
        "how-to guides, release notes, or product functionality. "
        "Returns documentation passages with source URLs."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "query": types.Schema(
                type="STRING",
                description="The search query to find relevant documentation pages.",
            ),
        },
        required=["query"],
    ),
)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

ROUTER_SYSTEM_PROMPT = """You are a query router for a knowledge agent that answers questions about:
1. Customer data (accounts, support issues, feature requests, tasks, meeting notes)
2. FlytBase platform documentation (docs.flytbase.com, releases.flytbase.com)

Given a user question, decide which tools to call:
- Call `search_customer_data` for questions about specific customers, accounts, issues, feature requests, tasks, or meeting notes.
- Call `fetch_docs` for questions about FlytBase platform features, capabilities, how-tos, or release notes.
- Call BOTH tools when the question requires combining customer data with platform documentation (e.g., "which accounts requested a feature that's already supported?").

You MUST call at least one tool. After receiving tool results, synthesize an answer following these citation rules:

CITATION RULES (MANDATORY):
1. Every factual claim MUST cite its source:
   - For customer data: cite the record ID (e.g., [acct-001], [ISS-0042], [FR-0003], [MTG-0015], [TASK-0022])
   - For documentation: cite the URL (e.g., [docs: https://docs.flytbase.com/path])
2. If you cannot find sufficient information to answer, say so explicitly: "I don't have enough information to answer this question."
3. Do NOT fabricate or guess information. Only state what is directly supported by the tool results.
4. When combining sources, clearly indicate which claims come from customer data vs. documentation.

FORMAT:
- Use markdown for formatting
- Put citations inline with the text, in square brackets
- At the end, include a "Sources" section listing all citations used"""

CONTRADICTION_CHECK_PROMPT = """You are analyzing whether customer feature requests have already been implemented in the FlytBase platform.

You will be given customer feature requests and documentation passages.

A VALID contradiction requires ALL of the following:
1. The feature request is listed as "new" or "in_progress" (NOT done/delivered).
2. The documentation EXPLICITLY describes the exact or near-identical feature as available functionality (it exists in the docs).
3. The match is DIRECT and factual — not speculative. Vague similarity, inferred capability, or "this feature could be used to achieve similar functionality" is NOT a contradiction.

Output ONLY a JSON array of contradictions. Each item:
{
  "feature_request_id": "FR-0005",
  "title": "Short feature title",
  "requesting_accounts": ["Account A", "Account B"],
  "doc_url": "https://docs.flytbase.com/...",
  "explanation": "One or two sentences, purely factual: what the docs say, and why it directly matches the requested feature."
}

RULES:
- Exclude any match that is speculative, vague, "not a clear match", "could be used to", "might be related", or only partially overlapping.
- If no clear contradictions exist, output: []
- Output ONLY the JSON array — no preamble, no commentary."""

SYNTHESIS_SYSTEM_PROMPT = """You are a knowledge agent answering questions about:
1. Customer data (accounts, support issues, feature requests, tasks, meeting notes)
2. FlytBase platform documentation (docs.flytbase.com, releases.flytbase.com)

You will be given a user question followed by search results from both sources.
Synthesize a single, well-organized answer using ONLY the provided results. Do NOT call any tools.

CITATION RULES (MANDATORY):
1. Every factual claim MUST cite its source:
   - For customer data: cite the record ID (e.g., [acct-001], [ISS-0042], [FR-0003], [MTG-0015], [TASK-0022])
   - For documentation: cite the URL (e.g., [docs: https://docs.flytbase.com/path])
2. If you cannot find sufficient information to answer, say so explicitly: "I don't have enough information to answer this question."
3. Do NOT fabricate or guess information. Only state what is directly supported by the results.
4. When combining sources, clearly indicate which claims come from customer data vs. documentation.
5. Irrelevant results should be ignored — do not force them into the answer.

FORMAT:
- Use markdown for formatting
- Put citations inline with the text, in square brackets
- At the end, include a "Sources" section listing all citations used"""


# ---------------------------------------------------------------------------
# LLM call functions
# ---------------------------------------------------------------------------

async def route_and_synthesize(
    question: str,
    search_fn,  # async callable(query, record_type, account_name, industry) -> results
    docs_fn,    # async callable(query) -> passages
) -> dict:
    """
    Main orchestration: route the question to appropriate tools,
    gather results, and synthesize a cited answer.
    Falls back: Gemini -> Groq -> Local synthesis.
    """
    # Step 1: Search customer data up-front so we always have data for any fallback
    import asyncio
    search_task = search_fn(query=question)
    customer_data_results = await search_task

    if isinstance(customer_data_results, Exception):
        print(f"[llm] Customer search failed: {customer_data_results}")
        customer_data_results = []

    # If we found feature requests, build a targeted docs query from their titles.
    # This makes "which requested feature does the platform already support" land on real doc pages.
    fr_results = [r for r in customer_data_results
                  if r.get("metadata", {}).get("record_type") == "feature_request"]
    docs_query = question
    if fr_results:
        import re
        fr_titles = []
        for r in fr_results[:5]:
            content = r.get("content", "")
            title = content.split("\n")[0] if content else ""
            title = title.replace("Feature Request:", "").strip()
            title = re.sub(r"\(ID:\s*FR-\d+\)", "", title).strip()
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                fr_titles.append(title[:100])
        if fr_titles:
            docs_query = " ".join(fr_titles[:3])
            print(f"[llm] Targeted docs query from feature requests: {docs_query[:200]}")

    docs_results = await docs_fn(query=docs_query)
    if isinstance(docs_results, Exception):
        print(f"[llm] Docs fetch failed: {docs_results}")
        docs_results = []

    sources_used = set()
    all_citations = []
    if customer_data_results:
        sources_used.add("customer_data")
        for r in customer_data_results:
            all_citations.append({
                "id": r["id"],
                "type": "customer_data",
                "record_type": r.get("metadata", {}).get("record_type", ""),
                "content_preview": r["content"][:200],
            })
    if docs_results:
        sources_used.add("docs")
        for p in docs_results:
            all_citations.append({
                "id": p.url,
                "type": "docs",
                "url": p.url,
                "title": p.title,
                "content_preview": p.content[:200],
                "source_site": p.source_site,
            })

    # Dedupe citations by ID (search can return the same record/page multiple times)
    seen_ids = set()
    deduped_citations = []
    for c in all_citations:
        cid = c.get("id", "")
        if cid and cid in seen_ids:
            continue
        seen_ids.add(cid)
        deduped_citations.append(c)
    all_citations = deduped_citations

    # Step 2: Build message with question + tool results as context
    messages = [
        types.Content(role="user", parts=[types.Part(text=question)]),
    ]

    tool_results_text = []
    if customer_data_results:
        tool_results_text.append("CUSTOMER DATA RESULTS:")
        for r in customer_data_results[:8]:
            tool_results_text.append(f"[{r['id']}] {r['content']}")
    if docs_results:
        tool_results_text.append("\nDOCUMENTATION RESULTS:")
        for p in docs_results[:5]:
            tool_results_text.append(f"[{p.url}]\nTitle: {p.title}\n{p.content[:1500]}")

    if tool_results_text:
        messages.append(
            types.Content(role="user", parts=[types.Part(text="\n\n".join(tool_results_text))])
        )

    # Step 3: Try Gemini, then Groq, then local synthesis
    answer = await _call_gemini(messages, system_instruction=SYNTHESIS_SYSTEM_PROMPT)

    if not answer:
        print("[llm] Falling back to Groq...")
        answer = await _call_grok(messages, system_instruction=SYNTHESIS_SYSTEM_PROMPT)

    if not answer:
        print("[llm] Falling back to local synthesis...")
        return _local_synthesis(question, customer_data_results, docs_results, sources_used)

    return {
        "answer": answer,
        "sources_used": list(sources_used),
        "citations": all_citations,
        "contradictions": [],
    }


async def check_contradictions(
    feature_requests: list[dict],
    docs_passages: list,
) -> list[dict]:
    """
    Check for contradictions between feature requests and docs.
    Returns list of contradiction findings.
    Falls back: Gemini -> Grok -> Local check.
    """
    if not feature_requests or not docs_passages:
        return []

    # Dedupe by ID
    seen = set()
    feature_requests = [r for r in feature_requests
                        if not (r["id"] in seen or seen.add(r["id"]))]

    # Build context
    fr_text = "\n\n".join([
        f"[{r['id']}] {r['content']}" for r in feature_requests
    ])
    docs_text = "\n\n---\n\n".join([
        f"[{p.url}]\nTitle: {p.title}\n{p.content[:1500]}"
        for p in docs_passages
    ])

    prompt = (
        f"CUSTOMER FEATURE REQUESTS:\n{fr_text}\n\n"
        f"DOCUMENTATION / RELEASE NOTES:\n{docs_text}\n\n"
        f"Analyze the above and identify any contradictions."
    )

    messages = [
        types.Content(role="user", parts=[types.Part(text=prompt)]),
    ]

    # Try Gemini
    text = await _call_gemini(messages, system_instruction=CONTRADICTION_CHECK_PROMPT)
    
    # Fallback to Grok
    if not text:
        print("[llm] Contradiction check: falling back to Grok...")
        text = await _call_grok(messages, system_instruction=CONTRADICTION_CHECK_PROMPT)
    
    # Local fallback: simple keyword matching
    if not text:
        print("[llm] Contradiction check: using local fallback...")
        text = _local_contradiction_check(feature_requests, docs_passages)

    if not text:
        return []

    findings = _parse_contradictions(text)
    # Verify each finding against the actual FR data (no hallucinated IDs)
    valid_ids = {r["id"] for r in feature_requests}
    validated = []
    for f in findings:
        fr_id = f.get("feature_request_id", "")
        if fr_id and fr_id not in valid_ids:
            continue
        validated.append(f)
    return validated


def _parse_contradictions(text: str) -> list[dict]:
    """Parse the LLM's JSON array output; drop speculative/weak findings."""
    import re

    weak_markers = re.compile(
        r"could\s+be\s+used|might\s+be\s+related|not\s+a\s+clear\s+match|"
        r"not\s+explicitly|not\s+entirely\s+clear|possibly|may\s+be\s+similar|"
        r"could\s+be\s+considered|might\s+be\s+relevant|similar\s+functionality",
        re.IGNORECASE,
    )

    # Extract the JSON array from the response
    m = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
    if m:
        try:
            items = json.loads(m.group(0))
        except Exception:
            items = []
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if not it.get("feature_request_id") and not it.get("title"):
                continue
            expl = (it.get("explanation") or "").strip()
            if weak_markers.search(expl):
                continue
            out.append({
                "feature_request_id": it.get("feature_request_id", ""),
                "title": (it.get("title") or "").strip(),
                "requesting_accounts": it.get("requesting_accounts") or [],
                "doc_url": (it.get("doc_url") or "").strip(),
                "explanation": expl,
                "analysis": (
                    f"[{it.get('feature_request_id', 'FR-?')}] {it.get('title', '')} "
                    f"— already documented: {it.get('doc_url', '')}. {expl}"
                ).strip(),
            })
        return out

    # No JSON array found: treat empty/negated output as "no contradiction"
    stripped = text.strip().strip('`"').strip().lower()
    if not stripped or stripped in ("[]", "none", "no contradictions", "no contradiction",
                                     "no clear contradictions", "no contradictions found",
                                     "[] no contradictions found."):
        return []
    if re.search(r"no\s+clear|no\s+contradiction|not\s+a\s+clear\s+match|could\s+be\s+used",
                 text, re.IGNORECASE):
        return []
    # Only accept unstructured output if it actually names a feature request or doc URL
    if re.search(r"FR-\d+|https?://", text, re.IGNORECASE):
        return [{"analysis": text.strip()}]
    return []


def _local_contradiction_check(feature_requests: list[dict], docs_passages: list) -> str:
    """Simple local contradiction detection via keyword overlap."""
    # Extract key terms from feature requests
    fr_keywords = set()
    for r in feature_requests:
        content = r.get("content", "").lower()
        # Extract meaningful words (simple approach)
        words = [w for w in content.split() if len(w) > 4]
        fr_keywords.update(words[:20])  # top 20 per request
    
    # Check docs for similar terms
    for p in docs_passages:
        doc_content = p.content.lower()
        matches = [kw for kw in fr_keywords if kw in doc_content]
        if len(matches) >= 3:  # threshold
            return (f"Potential contradiction detected: Feature request mentions "
                    f"'{', '.join(matches[:5])}' which also appear in documentation "
                    f"({p.title}). Manual verification recommended.")
    
    return "No contradictions found (local check)."
