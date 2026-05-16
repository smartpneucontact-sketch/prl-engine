"""
PRL RAG Engine v3 — Five-Layer Policy Reasoning Architecture

Layer 1: Ingestion Engine — Document processing, chunking, vector storage with source tagging
Layer 2: Query Processor — Intent interpretation, clarifying questions when ambiguous
Layer 3: Retrieval Engine — Semantic search, ranked citations with source attribution
Layer 4: Reasoning Engine — Chain-of-thought logic, visible reasoning, edge case flagging
Layer 5: Output Generator — Structured multi-part output (Answer + Reasoning + Citations + Artifact)
"""

import os
import re
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UPLOAD_DIR = os.environ.get("PRL_UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "uploads"))
VECTOR_DIR = os.environ.get("PRL_VECTOR_DIR", os.path.join(os.path.dirname(__file__), "vectorstore"))
CHUNK_SIZE = int(os.environ.get("PRL_CHUNK_SIZE", 800))
CHUNK_OVERLAP = int(os.environ.get("PRL_CHUNK_OVERLAP", 150))
TOP_K = int(os.environ.get("PRL_TOP_K", 8))
SUMMARY_INPUT_CAP = int(os.environ.get("PRL_SUMMARY_CAP", 12000))
SUMMARY_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prl-summarizer")

# Pricing in USD per 1M tokens. Override via PRL_INPUT_COST / PRL_OUTPUT_COST env vars
# if the deployed model differs from the table below.
MODEL_PRICING = {
    "claude-sonnet-4-20250514":   {"input": 3.00,  "output": 15.00},
    "claude-sonnet-4-5":          {"input": 3.00,  "output": 15.00},
    "claude-sonnet-4-6":          {"input": 3.00,  "output": 15.00},
    "claude-opus-4-7":            {"input": 15.00, "output": 75.00},
    "claude-opus-4-7[1m]":        {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001":  {"input": 1.00,  "output": 5.00},
}
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


def _price_call(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a single Claude call given its token usage."""
    in_rate = float(os.environ.get("PRL_INPUT_COST", "") or
                    MODEL_PRICING.get(model, _DEFAULT_PRICING)["input"])
    out_rate = float(os.environ.get("PRL_OUTPUT_COST", "") or
                     MODEL_PRICING.get(model, _DEFAULT_PRICING)["output"])
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


def _log_api_usage(kind: str, model: str, response):
    """Extract token usage from an Anthropic response and persist it."""
    try:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        cost = _price_call(model, in_tok, out_tok)
        from database import record_api_usage
        record_api_usage(kind, model, in_tok, out_tok, cost)
    except Exception as e:
        logger.warning(f"Could not record API usage: {e}")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(VECTOR_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# PRL System Prompt v3 — Manager Ops Copilot (FAA TechOps PASS BWS & AWS)
# ---------------------------------------------------------------------------

_PROMPT_FILE = Path(__file__).parent / "PRL_System_Prompt_v3.txt"


def _load_system_prompt() -> str:
    """Load PRL system prompt from env var, then file, then fallback."""
    env_prompt = os.environ.get("SYSTEM_PROMPT", "").strip()
    if env_prompt:
        return env_prompt
    try:
        return _PROMPT_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"System prompt file not found at {_PROMPT_FILE}")
        return (
            "You are the PRL Manager Ops Copilot for FAA Technical Operations. "
            "Cite governing policy sections (PASS CBA Articles 31–35, HRPM LWS-8.14/8.15, "
            "Article 34 Fatigue Requirements) for every claim. End each response with "
            "Sources used / Governing authority / Risk flags / Recommended action."
        )


PRL_SYSTEM_PROMPT = _load_system_prompt()


# ---------------------------------------------------------------------------
# Layer 1 — Ingestion Engine: Text Extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from a PDF file."""
    try:
        import PyPDF2
        text_parts = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"[Page {i+1}]\n{page_text}")
        return "\n\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF extraction failed for {filepath}: {e}")
        return ""


def extract_text_from_docx(filepath: str) -> str:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        doc = Document(filepath)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX extraction failed for {filepath}: {e}")
        return ""


def extract_text_from_txt(filepath: str) -> str:
    """Extract text from a plain text file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        logger.error(f"TXT extraction failed for {filepath}: {e}")
        return ""


def extract_text(filepath: str) -> str:
    """Route to the correct extractor based on file extension."""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(filepath)
    elif ext in (".txt", ".md", ".csv"):
        return extract_text_from_txt(filepath)
    else:
        logger.warning(f"Unsupported file type: {ext}")
        return ""


# ---------------------------------------------------------------------------
# Layer 1 — Ingestion Engine: Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split text into overlapping chunks. Tries to split on paragraph/section boundaries first.
    Preserves page markers for citation accuracy.
    """
    if not text.strip():
        return []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current_chunk = ""
    chunk_index = 0
    current_page = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Track page markers
        page_match = re.match(r"\[Page (\d+)\]", para)
        if page_match:
            current_page = f"Page {page_match.group(1)}"
            para = re.sub(r"^\[Page \d+\]\s*", "", para)
            if not para:
                continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        else:
            if current_chunk:
                chunks.append({
                    "text": current_chunk.strip(),
                    "index": chunk_index,
                    "page": current_page,
                })
                chunk_index += 1
                words = current_chunk.split()
                overlap_words = words[-overlap // 4:] if len(words) > overlap // 4 else []
                current_chunk = " ".join(overlap_words) + "\n\n" + para if overlap_words else para
            else:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= chunk_size:
                        current_chunk = current_chunk + " " + sent if current_chunk else sent
                    else:
                        if current_chunk:
                            chunks.append({
                                "text": current_chunk.strip(),
                                "index": chunk_index,
                                "page": current_page,
                            })
                            chunk_index += 1
                        current_chunk = sent

    if current_chunk.strip():
        chunks.append({
            "text": current_chunk.strip(),
            "index": chunk_index,
            "page": current_page,
        })

    return chunks


# ---------------------------------------------------------------------------
# Layer 1 — Ingestion Engine: Vector Store (ChromaDB)
# ---------------------------------------------------------------------------

_client = None
_collection = None


def get_collection():
    """Get or create the ChromaDB collection."""
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=VECTOR_DIR)
        _collection = _client.get_or_create_collection(
            name="prl_policies",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def ingest_document(filepath: str, doc_name: str, doc_category: str = "general",
                    project_id: int = None) -> dict:
    """
    Layer 1 — Ingestion Pipeline:
    Extract text → chunk → embed → store in vector DB with rich metadata.
    Also creates a SQLite documents row and queues async summarization.
    """
    text = extract_text(filepath)
    if not text.strip():
        return {"status": "error", "message": "Could not extract text from document."}

    chunks = chunk_text(text)
    if not chunks:
        return {"status": "error", "message": "No content chunks produced."}

    collection = get_collection()
    doc_hash = hashlib.md5(filepath.encode()).hexdigest()[:10]

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        chunk_id = f"{doc_hash}_chunk_{chunk['index']}"
        ids.append(chunk_id)
        documents.append(chunk["text"])
        metadatas.append({
            "source": doc_name,
            "category": doc_category,
            "chunk_index": chunk["index"],
            "page": chunk.get("page", ""),
            "filepath": filepath,
            "ingested_at": datetime.utcnow().isoformat(),
        })

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    doc_id = None
    try:
        from database import upsert_document_row
        doc_id = upsert_document_row(doc_name, doc_category, len(chunks), project_id)
        SUMMARY_POOL.submit(_summarize_in_background, doc_id, text, doc_name, doc_category)
    except Exception as e:
        logger.warning(f"Could not register document row for summarization: {e}")

    return {
        "status": "success",
        "document": doc_name,
        "document_id": doc_id,
        "category": doc_category,
        "chunks": len(chunks),
        "total_chars": len(text),
        "summary_status": "pending",
    }


# ---------------------------------------------------------------------------
# Layer 1 — Auto-Summarization (background, structured JSON)
# ---------------------------------------------------------------------------

_SUMMARIZER_PROMPT = """You are a federal-policy document summarizer for the PRL Engine.
Read the document excerpt and produce a STRICT JSON object with these fields:

{
  "headline": "<≤80-char title-cased headline>",
  "summary_paragraph": "<2–3 sentence prose summary>",
  "document_type": "<one of: Incident Report | Policy Memo | CBA Article | HRPM Section | FAA Order | Letter | Management Guide | Local Procedure | Technical Bulletin | Other>",
  "key_dates": ["YYYY-MM-DD: <event>", ...],
  "parties_mentioned": ["<role or name>", ...],
  "policy_citations": ["<article/section/order reference>", ...],
  "action_items": ["<imperative phrase>", ...],
  "risk_flags": ["<compliance or grievance exposure>", ...]
}

Rules:
- Output ONLY the JSON object. No preamble, no markdown fences.
- Use empty arrays [] when a field has no content. Never invent facts.
- Dates must be ISO-8601 (YYYY-MM-DD) when extractable; omit otherwise.
- Citations should preserve exact reference style (e.g., "Article 31 Section 9", "HRPM LWS-8.14")."""


def summarize_document(text: str, doc_name: str, category: str) -> dict:
    """Call Claude to produce a structured JSON summary of a document."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    excerpt = text[:SUMMARY_INPUT_CAP]
    truncated_note = f"\n\n[NOTE: Document truncated to {SUMMARY_INPUT_CAP} chars; full length {len(text)}.]" \
        if len(text) > SUMMARY_INPUT_CAP else ""

    user_message = (
        f"DOCUMENT NAME: {doc_name}\n"
        f"CATEGORY: {category}\n"
        f"-----\n{excerpt}{truncated_note}\n-----\n"
        f"Produce the JSON summary."
    )

    model = os.environ.get("PRL_MODEL", "claude-sonnet-4-20250514")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1200,
        system=_SUMMARIZER_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _log_api_usage("summarize", model, response)
    raw = response.content[0].text.strip()

    # Strip accidental markdown fences if Claude wraps the JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    parsed = json.loads(raw)

    # Validate / normalize required keys
    defaults = {
        "headline": doc_name,
        "summary_paragraph": "",
        "document_type": "Other",
        "key_dates": [],
        "parties_mentioned": [],
        "policy_citations": [],
        "action_items": [],
        "risk_flags": [],
    }
    for k, v in defaults.items():
        parsed.setdefault(k, v)

    return parsed


def _summarize_in_background(doc_id: int, text: str, doc_name: str, category: str):
    """Worker that runs in the ThreadPoolExecutor; updates SQLite when done."""
    from database import mark_document_processing, save_document_summary, mark_document_failed
    try:
        mark_document_processing(doc_id)
        summary = summarize_document(text, doc_name, category)
        save_document_summary(doc_id, summary, summary.get("summary_paragraph", ""))
        logger.info(f"Summarized doc {doc_id} ({doc_name})")
    except Exception as e:
        logger.error(f"Summarization failed for doc {doc_id} ({doc_name}): {e}")
        try:
            mark_document_failed(doc_id, str(e)[:500])
        except Exception:
            pass


def get_document_full_text(doc_name: str) -> str:
    """Reassemble original document text by concatenating chunks from ChromaDB."""
    collection = get_collection()
    results = collection.get(where={"source": doc_name}, include=["documents", "metadatas"])
    if not results or not results.get("documents"):
        return ""
    pairs = list(zip(results["documents"], results["metadatas"] or []))
    pairs.sort(key=lambda p: p[1].get("chunk_index", 0) if p[1] else 0)
    return "\n\n".join(text for text, _ in pairs)


def resummarize_document(doc_id: int) -> dict:
    """Manually re-run summarization for a document. Returns status dict."""
    from database import get_document
    doc = get_document(doc_id)
    if not doc:
        return {"status": "error", "message": "Document not found"}
    text = get_document_full_text(doc["name"])
    if not text:
        return {"status": "error", "message": "Could not reassemble document text from ChromaDB"}
    SUMMARY_POOL.submit(_summarize_in_background, doc_id, text, doc["name"], doc["category"])
    return {"status": "queued", "document_id": doc_id}


def backfill_document_rows():
    """
    On startup: ensure every ChromaDB-known document has a SQLite documents row.
    Queue summarization for any row whose summary is pending or failed.
    Idempotent — safe to call on every boot.
    """
    try:
        from database import upsert_document_row, get_pending_documents
        stats = get_document_stats()
        for doc in stats["documents"]:
            upsert_document_row(doc["name"], doc["category"], doc["chunks"])

        pending = get_pending_documents()
        for row in pending:
            text = get_document_full_text(row["name"])
            if text:
                SUMMARY_POOL.submit(_summarize_in_background, row["id"], text, row["name"], row["category"])
        logger.info(f"Backfill: queued {len(pending)} document(s) for summarization")
    except Exception as e:
        logger.warning(f"Document backfill skipped: {e}")


# ---------------------------------------------------------------------------
# Layer 3 — Retrieval Engine: Semantic Search
# ---------------------------------------------------------------------------

def search_policies(query: str, top_k: int = TOP_K, category: str = None) -> list[dict]:
    """
    Layer 3 — Retrieval Engine:
    Semantic search with ranked citations and source attribution.
    """
    collection = get_collection()

    if collection.count() == 0:
        return []

    where_filter = {"category": category} if category else None

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    if results and results["documents"]:
        for i, doc_text in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0
            relevance = round(1 - distance, 4)
            output.append({
                "text": doc_text,
                "source": meta.get("source", "Unknown"),
                "category": meta.get("category", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "page": meta.get("page", ""),
                "relevance": relevance,
            })

    return output


def get_document_stats() -> dict:
    """Return statistics about the ingested documents."""
    collection = get_collection()
    total = collection.count()

    if total == 0:
        return {"total_chunks": 0, "documents": []}

    all_meta = collection.get(include=["metadatas"])
    sources = {}
    for meta in all_meta["metadatas"]:
        src = meta.get("source", "Unknown")
        cat = meta.get("category", "general")
        if src not in sources:
            sources[src] = {"name": src, "category": cat, "chunks": 0}
        sources[src]["chunks"] += 1

    return {
        "total_chunks": total,
        "documents": list(sources.values()),
    }


def delete_document(doc_name: str) -> dict:
    """Delete all chunks belonging to a specific document."""
    collection = get_collection()
    all_data = collection.get(include=["metadatas"])

    ids_to_delete = []
    for i, meta in enumerate(all_data["metadatas"]):
        if meta.get("source") == doc_name:
            ids_to_delete.append(all_data["ids"][i])

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
        try:
            from database import delete_document_row
            delete_document_row(doc_name)
        except Exception as e:
            logger.warning(f"Could not delete documents row for {doc_name}: {e}")
        return {"status": "deleted", "document": doc_name, "chunks_removed": len(ids_to_delete)}

    return {"status": "not_found", "document": doc_name}


# ---------------------------------------------------------------------------
# Layer 2 — Query Processor: Intent Interpretation
# ---------------------------------------------------------------------------

# Order matters — first matching bucket wins. Watch-schedule keywords come
# before leave keywords so "AWS" (Alternate Work Schedule) doesn't collide
# with annual leave terminology. Fatigue comes before discipline so
# "fatigue" + "remove" queries route to compliance, not removal action.
INTENT_BUCKETS = [
    ("watch_schedule_authority", [
        "bws", "basic watch schedule", "aws", "alternate work schedule",
        "watch schedule", "midshift", "mid shift", "scd", "rotation",
        "swap", "shift swap", "tour", "fixed line", "article 31",
        "article 32", "section 9", "section 6", "coverage", "staffing",
    ]),
    ("fatigue_compliance", [
        "fatigue", "rest period", "rest between shifts", "10 hours",
        "article 34", "minimum rest", "consecutive shifts",
    ]),
    ("overtime_premium", [
        "overtime", " ot ", "ot solicitation", "premium pay",
        "sunday pay", "holiday pay",
    ]),
    ("leave_request", [
        "leave", "lwop", "annual leave", "sick leave", "fmla",
        "credit hours", "comp time", "religious", "hrpm lws-8.14",
    ]),
    ("discipline_action", [
        "discipline", "reprimand", "counseling", "awol", "misconduct",
        "last chance", "proposal to remove",
    ]),
    ("union_collaboration", [
        "union", "pass", "cba", "bargain", "grievance", "article 10",
        "article 3", "collaboration", "notification", "mou",
    ]),
    ("tech_ops_maintenance", [
        "equipment", "maintenance", "nas", "outage", "circuit",
        "rcag", "asr", "atct", "vortac", "preventive", "corrective",
        "work order",
    ]),
    ("crisis_operations", [
        "furlough", "shutdown", "timecard", "coding", "continuity",
    ]),
]


def classify_query_intent(question: str) -> dict:
    """
    Layer 2 — Intent classification aligned with FAA TechOps Manager Ops Copilot.
    First-match-wins keyword routing across BWS/AWS, fatigue, leave, discipline,
    union, tech ops, and crisis buckets.
    """
    question_lower = question.lower().strip()

    intent = {
        "type": "policy_query",
        "needs_clarification": False,
        "clarification_prompt": "",
        "management_function": "general",
    }

    for bucket_name, keywords in INTENT_BUCKETS:
        if any(kw in question_lower for kw in keywords):
            intent["management_function"] = bucket_name
            break

    # Clarification gate: only trigger if the query is very short AND no domain
    # keyword matched. "BWS Q3?" (3 words, matches bws) flows through; "help me"
    # (2 words, no match) asks for context.
    if len(question.split()) < 3 and intent["management_function"] == "general":
        intent["needs_clarification"] = True
        intent["clarification_prompt"] = (
            "Your question is brief. Could you add context? For example:\n"
            "- Are you asking about BWS, AWS, leave, fatigue, or discipline?\n"
            "- Which employee, team, or facility is involved?\n"
            "- What is the timeframe (mid-cycle, Q3, immediate)?"
        )

    return intent


# ---------------------------------------------------------------------------
# Layer 4 + 5 — Reasoning Engine + Output Generator
# ---------------------------------------------------------------------------

def query_prl(question: str, top_k: int = TOP_K, project_id: int = None) -> dict:
    """
    Full PRL v3 Five-Layer Pipeline:
    1. Ingest (pre-done) → 2. Query Process → 3. Retrieve → 4. Reason → 5. Generate Output

    Returns structured response with answer, reasoning, citations, and metadata.
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "answer": "**CONFIGURATION REQUIRED**\n\n"
                      "ANTHROPIC_API_KEY not configured. To enable PRL reasoning:\n\n"
                      "1. Go to Railway → Your Project → Variables\n"
                      "2. Add: ANTHROPIC_API_KEY = sk-ant-...\n"
                      "3. Redeploy the service\n\n"
                      "Without the API key, the Knowledge Base and Search features still work, "
                      "but the reasoning engine cannot generate policy guidance.",
            "sources": [],
            "mode": "no_api_key",
            "reasoning_summary": "",
            "management_function": "",
            "decision_id": None,
        }

    # Layer 2 — Query Processing
    intent = classify_query_intent(question)

    if intent["needs_clarification"]:
        return {
            "answer": intent["clarification_prompt"],
            "sources": [],
            "mode": "clarification",
            "reasoning_summary": "Query was too brief for confident policy reasoning.",
            "management_function": intent["management_function"],
            "decision_id": None,
        }

    # Layer 3 — Retrieval
    results = search_policies(question, top_k=top_k)

    # Layer 3 — Build context from retrieved chunks (may be empty)
    context_parts = []
    sources_used = []
    for i, r in enumerate(results):
        page_info = f" | {r['page']}" if r.get("page") else ""
        context_parts.append(
            f"[SOURCE {i + 1}: {r['source']} | Category: {r['category']}{page_info} | Relevance: {r['relevance']}]\n{r['text']}"
        )
        if r["source"] not in [s["name"] for s in sources_used]:
            sources_used.append({
                "name": r["source"],
                "category": r["category"],
                "relevance": r["relevance"],
                "page": r.get("page", ""),
            })

    context_block = "\n\n---\n\n".join(context_parts)
    has_context = bool(results)
    mode_tag = "rag" if has_context else "general"

    # Layer 4 — Reasoning (Claude call). When context is empty, Claude can still
    # answer questions about the PRL Engine itself (using the APP ENVIRONMENT
    # section in its system prompt) or honestly state what's needed for policy
    # questions instead of refusing to engage.
    if has_context:
        user_message = (
            f"RETRIEVED POLICY CONTEXT:\n"
            f"========================\n"
            f"{context_block}\n\n"
            f"========================\n\n"
            f"MANAGEMENT FUNCTION: {intent['management_function']}\n\n"
            f"MANAGER'S QUESTION:\n{question}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Reason across ALL provided policy sources using chain-of-thought logic.\n"
            f"2. Cite specific documents, sections, and articles for every claim.\n"
            f"3. Identify the approval authority for any recommended action.\n"
            f"4. Flag any risks, grievance exposure, or compliance concerns.\n"
            f"5. Provide governance-ready recommended action language.\n"
            f"6. Show your reasoning chain so the manager can follow your logic.\n"
            f"7. If the context is insufficient, state exactly what is missing and what additional policy source is needed.\n"
            f"8. If the question is ambiguous, ask a clarifying question before forcing an answer."
        )
    else:
        user_message = (
            f"NO POLICY DOCUMENTS WERE RETRIEVED for this query. The Knowledge Base may be empty, "
            f"or no ingested document matched.\n\n"
            f"MANAGEMENT FUNCTION: {intent['management_function']}\n\n"
            f"MANAGER'S QUESTION:\n{question}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. If this is a META QUESTION about the PRL Engine app itself "
            f"(what it does, its features, tabs, capabilities, how to use it, how to get started, "
            f"what each tab is for, how Projects/Timeline/Audit Trail work, how to upload documents, "
            f"how to compose emails, which letter templates exist), answer it directly and helpfully "
            f"using your knowledge from the APP ENVIRONMENT section of your system prompt. "
            f"Be welcoming and guide the manager. Skip the citation footer for meta questions.\n"
            f"2. If this is a POLICY question, do NOT fabricate policy language. State exactly which "
            f"document(s) and section(s) would be needed (e.g., PASS CBA Article 31, HRPM LWS-8.14) "
            f"and instruct the manager to upload them via the Knowledge Base tab. Apply built-in "
            f"policy logic ONLY as general orientation, never as cited authority.\n"
            f"3. If the question is ambiguous, ask a brief clarifying question.\n"
            f"4. Always be helpful and route the manager to the right app feature for their next step."
        )

    try:
        model = os.environ.get("PRL_MODEL", "claude-sonnet-4-20250514")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=3000,
            system=PRL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        _log_api_usage("ask", model, response)
        answer = response.content[0].text
    except anthropic.AuthenticationError:
        answer = "**AUTHENTICATION ERROR**\n\nInvalid API key. Please check your ANTHROPIC_API_KEY in Railway variables."
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        answer = f"**API ERROR**\n\nError communicating with Claude API: {str(e)}"

    # Layer 5 — Output Generation: Extract reasoning summary
    reasoning_summary = _extract_reasoning_summary(answer)

    # Save to decision audit trail
    decision_id = None
    try:
        from database import save_decision
        decision_id = save_decision(
            question=question,
            answer=answer,
            sources=sources_used,
            reasoning_summary=reasoning_summary,
            mode=mode_tag,
            chunks_used=len(results),
            project_id=project_id,
        )
    except Exception as e:
        logger.warning(f"Could not save decision to audit trail: {e}")

    return {
        "answer": answer,
        "sources": sources_used,
        "mode": mode_tag,
        "chunks_used": len(results),
        "reasoning_summary": reasoning_summary,
        "management_function": intent["management_function"],
        "decision_id": decision_id,
    }


def _extract_reasoning_summary(answer: str) -> str:
    """Extract the reasoning chain section from the PRL response."""
    patterns = [
        r"\*\*REASONING CHAIN\*\*\s*\n(.*?)(?=\n\*\*|\Z)",
        r"REASONING CHAIN[:\s]*\n(.*?)(?=\n[A-Z]{2,}|\Z)",
    ]
    for pattern in patterns:
        match = re.search(pattern, answer, re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""
