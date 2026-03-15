"""
PRL RAG Engine — Policy Reasoning Layer
Document ingestion, chunking, vector retrieval, and Claude-powered policy reasoning.
"""

import os
import re
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

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

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(VECTOR_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# PRL System Prompt — The Policy Reasoning Layer
# ---------------------------------------------------------------------------

PRL_SYSTEM_PROMPT = """You are PRL — the Policy Reasoning Layer — an AI decision-support system designed 
for operational managers in policy-dense organizations.

YOUR ROLE:
- You are a Policy GPS. Managers drive. You navigate.
- You reason ACROSS multiple policy frameworks simultaneously: CBA articles, HRPM sections, 
  agency orders, management guides, local procedures, and memoranda.
- You produce cited, structured, defensible guidance — never opinions, never guesses.

YOUR RULES (HARD CONSTRAINTS):
- ALWAYS cite the exact source document, section, and article for every claim.
- NEVER fabricate policy language. If you cannot find it in the provided context, say so explicitly.
- NEVER present union language as management position or vice versa.
- NEVER make a decision. You INFORM the decision. The manager retains all authority.
- ALWAYS identify: (1) the applicable rule, (2) the approval authority, (3) conditions or requirements, 
  (4) potential risks or grievance exposure, (5) recommended action language.
- When policies conflict or overlap, identify BOTH positions and explain the tension.
- Flag when human judgment is required beyond what policy can resolve.

YOUR OUTPUT FORMAT:
For every policy question, structure your response as:

📋 APPLICABLE GUIDANCE
[Cite specific sections, articles, and documents that apply]

✅ ANSWER
[Direct answer to the manager's question with conditions]

⚖️ AUTHORITY
[Who has approval authority for this action]

⚠️ RISKS / CONSIDERATIONS  
[Grievance exposure, compliance issues, or edge cases]

📝 RECOMMENDED ACTION
[Specific language or steps the manager can take]

If the provided context does not contain enough information to answer confidently, 
state exactly what is missing and what additional policy source would be needed.

You exist to reduce decision friction — to give managers confidence, consistency, and speed 
when navigating complex overlapping rule systems."""


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from a PDF file."""
    try:
        import PyPDF2
        text_parts = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
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
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split text into overlapping chunks. Tries to split on paragraph/section boundaries first.
    Returns list of dicts with 'text' and 'index' keys.
    """
    if not text.strip():
        return []

    # Split on double newlines (paragraphs) first
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current_chunk = ""
    chunk_index = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        else:
            if current_chunk:
                chunks.append({"text": current_chunk.strip(), "index": chunk_index})
                chunk_index += 1
                # Overlap: keep tail of current chunk
                words = current_chunk.split()
                overlap_words = words[-overlap // 4:] if len(words) > overlap // 4 else []
                current_chunk = " ".join(overlap_words) + "\n\n" + para if overlap_words else para
            else:
                # Single paragraph exceeds chunk_size — split by sentences
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= chunk_size:
                        current_chunk = current_chunk + " " + sent if current_chunk else sent
                    else:
                        if current_chunk:
                            chunks.append({"text": current_chunk.strip(), "index": chunk_index})
                            chunk_index += 1
                        current_chunk = sent

    if current_chunk.strip():
        chunks.append({"text": current_chunk.strip(), "index": chunk_index})

    return chunks


# ---------------------------------------------------------------------------
# Vector Store (ChromaDB)
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


def ingest_document(filepath: str, doc_name: str, doc_category: str = "general") -> dict:
    """
    Extract text from a document, chunk it, and store embeddings in ChromaDB.
    Returns metadata about the ingestion.
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
            "filepath": filepath,
            "ingested_at": datetime.utcnow().isoformat(),
        })

    # Upsert (idempotent — safe to re-ingest)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    return {
        "status": "success",
        "document": doc_name,
        "category": doc_category,
        "chunks": len(chunks),
        "total_chars": len(text),
    }


def search_policies(query: str, top_k: int = TOP_K, category: str = None) -> list[dict]:
    """
    Search the vector store for policy chunks relevant to a query.
    Returns list of results with text, source, and relevance score.
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
            output.append({
                "text": doc_text,
                "source": meta.get("source", "Unknown"),
                "category": meta.get("category", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "relevance": round(1 - distance, 4),  # cosine similarity
            })

    return output


def get_document_stats() -> dict:
    """Return statistics about the ingested documents."""
    collection = get_collection()
    total = collection.count()

    if total == 0:
        return {"total_chunks": 0, "documents": []}

    # Get unique documents
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
        return {"status": "deleted", "document": doc_name, "chunks_removed": len(ids_to_delete)}

    return {"status": "not_found", "document": doc_name}


# ---------------------------------------------------------------------------
# Claude-Powered Policy Reasoning
# ---------------------------------------------------------------------------

def query_prl(question: str, top_k: int = TOP_K) -> dict:
    """
    Full PRL pipeline: retrieve relevant policy chunks, then reason with Claude.
    Returns the answer and the sources used.
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "answer": "⚠️ ANTHROPIC_API_KEY not configured.\n\n"
                      "To enable PRL reasoning, set the ANTHROPIC_API_KEY environment variable "
                      "in your Railway project settings.\n\n"
                      "Go to Railway → Your Project → Variables → Add:\n"
                      "ANTHROPIC_API_KEY = sk-ant-...",
            "sources": [],
            "mode": "no_api_key",
        }

    # Step 1: Retrieve relevant policy chunks
    results = search_policies(question, top_k=top_k)

    if not results:
        return {
            "answer": "📂 No policy documents have been ingested yet.\n\n"
                      "Upload documents using the Knowledge Base tab to enable policy reasoning.\n"
                      "Supported formats: PDF, DOCX, TXT.",
            "sources": [],
            "mode": "no_documents",
        }

    # Step 2: Build context from retrieved chunks
    context_parts = []
    sources_used = []
    for i, r in enumerate(results):
        context_parts.append(
            f"[SOURCE {i + 1}: {r['source']} | Relevance: {r['relevance']}]\n{r['text']}"
        )
        if r["source"] not in [s["name"] for s in sources_used]:
            sources_used.append({
                "name": r["source"],
                "category": r["category"],
                "relevance": r["relevance"],
            })

    context_block = "\n\n---\n\n".join(context_parts)

    # Step 3: Call Claude with PRL system prompt + retrieved context
    user_message = (
        f"RETRIEVED POLICY CONTEXT:\n"
        f"========================\n"
        f"{context_block}\n\n"
        f"========================\n\n"
        f"MANAGER'S QUESTION:\n{question}\n\n"
        f"Reason across ALL provided policy sources. Cite specific documents and sections. "
        f"If the context is insufficient, state exactly what is missing."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=os.environ.get("PRL_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=2000,
            system=PRL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer = response.content[0].text
    except anthropic.AuthenticationError:
        answer = "⚠️ Invalid API key. Please check your ANTHROPIC_API_KEY in Railway variables."
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        answer = f"⚠️ Error communicating with Claude API: {str(e)}"

    return {
        "answer": answer,
        "sources": sources_used,
        "mode": "rag",
        "chunks_used": len(results),
    }
