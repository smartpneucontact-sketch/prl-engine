"""
PRL Engine v3.0 — Policy Reasoning Layer
Flask application with 5-layer RAG architecture, persistent data, and governance-ready outputs.

CJD Global Defense Contracting LLC
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename

from flask import Flask, render_template, jsonify, request

from rag_engine import (
    ingest_document,
    query_prl,
    get_document_stats,
    delete_document,
    search_policies,
    backfill_document_rows,
    resummarize_document,
    UPLOAD_DIR,
)

from database import (
    init_db,
    get_schedule,
    create_schedule_event,
    update_schedule_event,
    delete_schedule_event,
    get_emails,
    create_email,
    mark_email_read,
    get_letters,
    create_letter,
    get_governance,
    create_governance_item,
    update_governance_item,
    get_decisions,
    update_decision_feedback,
    save_feedback,
    get_feedback,
    get_dashboard_stats,
    get_projects,
    get_project,
    create_project,
    update_project,
    delete_project,
    get_project_timeline,
    get_documents_with_summaries,
    get_document,
    assign_document_project,
)

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

DOC_CATEGORIES = [
    "CBA / Bargaining",
    "HRPM",
    "Management Guide",
    "Memo",
    "FAA Order",
    "Local Procedure",
    "Technical Bulletin",
    "HR Guidance",
    "Labor Relations",
    "Other",
]

EMAIL_RECIPIENTS = ["ETR", "HR", "Supervisor", "AIT Leadership", "PASS Union Rep", "FAA Legal"]

# Initialize database on startup, then backfill any documents missing summaries
init_db()
backfill_document_rows()

# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — Dashboard Stats
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    stats = get_dashboard_stats()
    doc_stats = get_document_stats()
    stats["documents_ingested"] = len(doc_stats["documents"])
    stats["total_chunks"] = doc_stats["total_chunks"]
    return jsonify(stats)


# ---------------------------------------------------------------------------
# Routes — Schedule (CRUD)
# ---------------------------------------------------------------------------

@app.route("/api/schedule")
def api_schedule():
    return jsonify(get_schedule())

@app.route("/api/schedule", methods=["POST"])
def api_schedule_create():
    return jsonify(create_schedule_event(request.json))

@app.route("/api/schedule/<int:event_id>", methods=["PUT"])
def api_schedule_update(event_id):
    return jsonify(update_schedule_event(event_id, request.json))

@app.route("/api/schedule/<int:event_id>", methods=["DELETE"])
def api_schedule_delete(event_id):
    return jsonify(delete_schedule_event(event_id))


# ---------------------------------------------------------------------------
# Routes — Email (CRUD)
# ---------------------------------------------------------------------------

@app.route("/api/emails")
def api_emails():
    sent = request.args.get("sent", "false") == "true"
    return jsonify(get_emails(sent=sent))

@app.route("/api/emails/send", methods=["POST"])
def api_send_email():
    return jsonify(create_email(request.json))

@app.route("/api/emails/<int:email_id>/read", methods=["POST"])
def api_mark_read(email_id):
    return jsonify(mark_email_read(email_id))

@app.route("/api/recipients")
def api_recipients():
    return jsonify(EMAIL_RECIPIENTS)


# ---------------------------------------------------------------------------
# Routes — Letters
# ---------------------------------------------------------------------------

@app.route("/api/letters")
def api_letters():
    return jsonify(get_letters())

@app.route("/api/letters", methods=["POST"])
def api_letters_create():
    return jsonify(create_letter(request.json))


# ---------------------------------------------------------------------------
# Routes — Governance (CRUD)
# ---------------------------------------------------------------------------

@app.route("/api/governance")
def api_governance():
    return jsonify(get_governance())

@app.route("/api/governance", methods=["POST"])
def api_governance_create():
    return jsonify(create_governance_item(request.json))

@app.route("/api/governance/<int:item_id>", methods=["PUT"])
def api_governance_update(item_id):
    return jsonify(update_governance_item(item_id, request.json))


# ---------------------------------------------------------------------------
# Routes — Categories
# ---------------------------------------------------------------------------

@app.route("/api/categories")
def api_categories():
    return jsonify(DOC_CATEGORIES)


# ---------------------------------------------------------------------------
# Routes — RAG / Knowledge Base
# ---------------------------------------------------------------------------

@app.route("/api/documents", methods=["GET"])
def api_documents():
    """Return ChromaDB stats merged with SQLite summary metadata."""
    stats = get_document_stats()
    summaries = {d["name"]: d for d in get_documents_with_summaries()}
    enriched = []
    for doc in stats["documents"]:
        s = summaries.get(doc["name"], {})
        enriched.append({
            **doc,
            "id": s.get("id"),
            "project_id": s.get("project_id"),
            "project_name": s.get("project_name"),
            "summary_status": s.get("summary_status", "pending"),
            "summary_text": s.get("summary_text", ""),
            "summary_json": s.get("summary_json", {}),
            "summary_error": s.get("summary_error", ""),
            "summarized_at": s.get("summarized_at"),
        })
    return jsonify({"total_chunks": stats["total_chunks"], "documents": enriched})


@app.route("/api/documents/<int:doc_id>")
def api_document_detail(doc_id):
    doc = get_document(doc_id)
    if not doc:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify(doc)


@app.route("/api/documents/<int:doc_id>/resummarize", methods=["POST"])
def api_resummarize(doc_id):
    return jsonify(resummarize_document(doc_id))


@app.route("/api/documents/<int:doc_id>/project", methods=["PUT"])
def api_document_assign_project(doc_id):
    data = request.json or {}
    return jsonify(assign_document_project(doc_id, data.get("project_id")))


@app.route("/api/documents/upload", methods=["POST"])
def api_upload_document():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file provided."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"status": "error", "message": "No file selected."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "status": "error",
            "message": f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.",
        }), 400

    category = request.form.get("category", "Other")
    doc_name = request.form.get("name", file.filename)
    project_id_raw = request.form.get("project_id", "")
    project_id = int(project_id_raw) if project_id_raw.isdigit() else None

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    result = ingest_document(filepath, doc_name, category, project_id=project_id)
    return jsonify(result)

@app.route("/api/documents/delete", methods=["POST"])
def api_delete_document():
    data = request.json
    doc_name = data.get("name", "")
    if not doc_name:
        return jsonify({"status": "error", "message": "No document name provided."}), 400
    result = delete_document(doc_name)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes — Projects
# ---------------------------------------------------------------------------

@app.route("/api/projects")
def api_projects():
    return jsonify(get_projects())

@app.route("/api/projects", methods=["POST"])
def api_projects_create():
    data = request.json or {}
    if not data.get("name", "").strip():
        return jsonify({"status": "error", "message": "Project name required"}), 400
    return jsonify(create_project(data))

@app.route("/api/projects/<int:project_id>")
def api_project_detail(project_id):
    p = get_project(project_id)
    if not p:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify(p)

@app.route("/api/projects/<int:project_id>", methods=["PUT"])
def api_project_update(project_id):
    return jsonify(update_project(project_id, request.json or {}))

@app.route("/api/projects/<int:project_id>", methods=["DELETE"])
def api_project_delete(project_id):
    return jsonify(delete_project(project_id))

@app.route("/api/projects/<int:project_id>/timeline")
def api_project_timeline(project_id):
    types = request.args.get("types", "")
    type_list = [t.strip() for t in types.split(",") if t.strip()] or None
    start_date = request.args.get("start") or None
    end_date = request.args.get("end") or None
    return jsonify(get_project_timeline(project_id, type_list, start_date, end_date))


# ---------------------------------------------------------------------------
# Routes — PRL Query (5-Layer RAG Pipeline)
# ---------------------------------------------------------------------------

@app.route("/api/ask", methods=["POST"])
def api_ask():
    """PRL Decision Engine — Full 5-layer reasoning pipeline."""
    data = request.json
    question = data.get("question", "").strip()
    project_id = data.get("project_id")

    if not question:
        return jsonify({
            "answer": "Please enter a question.",
            "sources": [],
            "mode": "error",
            "reasoning_summary": "",
            "management_function": "",
            "decision_id": None,
        })

    result = query_prl(question, project_id=project_id)
    return jsonify(result)

@app.route("/api/search", methods=["POST"])
def api_search():
    """Direct vector search without Claude reasoning."""
    data = request.json
    query = data.get("query", "").strip()
    category = data.get("category", None)

    if not query:
        return jsonify({"results": []})

    results = search_policies(query, category=category)
    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# Routes — Decision Audit Trail
# ---------------------------------------------------------------------------

@app.route("/api/decisions")
def api_decisions():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_decisions(limit))

@app.route("/api/decisions/<int:decision_id>/feedback", methods=["POST"])
def api_decision_feedback(decision_id):
    data = request.json
    status = data.get("status", "reviewed")
    notes = data.get("notes", "")
    reviewer = data.get("reviewer", "")
    save_feedback(decision_id, status, notes, reviewer)
    return jsonify({"status": "saved"})


# ---------------------------------------------------------------------------
# Routes — Institutional Memory (Feedback Loop)
# ---------------------------------------------------------------------------

@app.route("/api/feedback")
def api_feedback():
    limit = request.args.get("limit", 100, type=int)
    return jsonify(get_feedback(limit))


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    stats = get_document_stats()
    db_stats = get_dashboard_stats()
    return jsonify({
        "status": "ok",
        "version": "3.0.0",
        "engine": "PRL — Policy Reasoning Layer",
        "architecture": "Five-Layer RAG",
        "documents_ingested": len(stats["documents"]),
        "total_chunks": stats["total_chunks"],
        "total_decisions": db_stats["total_decisions"],
        "approval_rate": db_stats["approval_rate"],
        "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "timestamp": datetime.utcnow().isoformat(),
    })


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
