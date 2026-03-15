"""
PRL Engine v2 — Predictive Readiness Loop
Flask application with RAG-powered policy decision support.
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
    UPLOAD_DIR,
)

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max upload
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

# ---------------------------------------------------------------------------
# Simulated Data (Schedule, Emails, Governance, Letters)
# ---------------------------------------------------------------------------

SCHEDULE_DATA = [
    {"id": 1, "date": "2026-03-16", "title": "NAS Equipment Review", "priority": "high"},
    {"id": 2, "date": "2026-03-17", "title": "Predictive Maintenance Sync", "priority": "medium"},
    {"id": 3, "date": "2026-03-20", "title": "PRL Stakeholder Briefing", "priority": "high"},
    {"id": 4, "date": "2026-03-22", "title": "Outage Pattern Analysis", "priority": "low"},
    {"id": 5, "date": "2026-03-24", "title": "ESU Environmental Trends Review", "priority": "medium"},
]

EMAILS_DATA = [
    {"id": 1, "from": "NAS Ops", "subject": "Outage Report — Sector 7 TRACON", "time": "2h ago", "read": False},
    {"id": 2, "from": "ETR Division", "subject": "Equipment refresh timeline update", "time": "5h ago", "read": True},
    {"id": 3, "from": "HR", "subject": "Re: Staffing matrix Q2", "time": "1d ago", "read": True},
]

GOVERNANCE_DATA = [
    {"id": 1, "title": "OMB Circular A-130", "category": "Federal", "status": "Active"},
    {"id": 2, "title": "FAA Order 1370.121", "category": "FAA/DOT", "status": "Active"},
    {"id": 3, "title": "Executive Order on AI", "category": "Federal", "status": "Under Review"},
    {"id": 4, "title": "DOT Data Governance Policy", "category": "FAA/DOT", "status": "Active"},
    {"id": 5, "title": "NIST AI RMF", "category": "Regulatory", "status": "Reference"},
]

LETTER_TEMPLATES = [
    {"id": 1, "title": "Letter of Counseling", "type": "Disciplinary"},
    {"id": 2, "title": "Letter of Reprimand", "type": "Disciplinary"},
    {"id": 3, "title": "Commendation Letter", "type": "Recognition"},
    {"id": 4, "title": "Proposal to Remove", "type": "Disciplinary"},
    {"id": 5, "title": "Last Chance Agreement", "type": "Settlement"},
]

EMAIL_RECIPIENTS = ["ETR", "HR", "Supervisor", "AIT Leadership"]

DOC_CATEGORIES = [
    "CBA / Bargaining",
    "HRPM",
    "Management Guide",
    "Memo",
    "FAA Order",
    "Local Procedure",
    "Other",
]

# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — Data APIs
# ---------------------------------------------------------------------------

@app.route("/api/schedule")
def api_schedule():
    return jsonify(SCHEDULE_DATA)


@app.route("/api/emails")
def api_emails():
    return jsonify(EMAILS_DATA)


@app.route("/api/governance")
def api_governance():
    return jsonify(GOVERNANCE_DATA)


@app.route("/api/letters")
def api_letters():
    return jsonify(LETTER_TEMPLATES)


@app.route("/api/recipients")
def api_recipients():
    return jsonify(EMAIL_RECIPIENTS)


@app.route("/api/categories")
def api_categories():
    return jsonify(DOC_CATEGORIES)


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    data = request.json
    return jsonify({
        "status": "sent",
        "to": data.get("to", []),
        "subject": data.get("subject", ""),
        "timestamp": datetime.utcnow().isoformat(),
    })


# ---------------------------------------------------------------------------
# Routes — RAG / Knowledge Base
# ---------------------------------------------------------------------------

@app.route("/api/documents", methods=["GET"])
def api_documents():
    """Get stats about all ingested documents."""
    stats = get_document_stats()
    return jsonify(stats)


@app.route("/api/documents/upload", methods=["POST"])
def api_upload_document():
    """Upload and ingest a policy document."""
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

    # Save file
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    # Ingest into vector store
    result = ingest_document(filepath, doc_name, category)
    return jsonify(result)


@app.route("/api/documents/delete", methods=["POST"])
def api_delete_document():
    """Delete a document from the knowledge base."""
    data = request.json
    doc_name = data.get("name", "")
    if not doc_name:
        return jsonify({"status": "error", "message": "No document name provided."}), 400
    result = delete_document(doc_name)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes — PRL Query (RAG-powered)
# ---------------------------------------------------------------------------

@app.route("/api/ask", methods=["POST"])
def api_ask():
    """
    PRL Decision Engine query.
    Retrieves relevant policy chunks and reasons with Claude.
    """
    data = request.json
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"answer": "Please enter a question.", "sources": [], "mode": "error"})

    result = query_prl(question)
    return jsonify(result)


@app.route("/api/search", methods=["POST"])
def api_search():
    """Direct vector search without Claude reasoning (faster, for reference lookups)."""
    data = request.json
    query = data.get("query", "").strip()
    category = data.get("category", None)

    if not query:
        return jsonify({"results": []})

    results = search_policies(query, category=category)
    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    stats = get_document_stats()
    return jsonify({
        "status": "ok",
        "version": "2.0.0",
        "engine": "PRL — Policy Reasoning Layer",
        "documents_ingested": stats["total_chunks"],
        "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "timestamp": datetime.utcnow().isoformat(),
    })


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
