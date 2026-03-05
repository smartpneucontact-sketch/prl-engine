from flask import Flask, render_template, jsonify, request
from datetime import datetime

app = Flask(__name__)

# --- Simulated Data ---

SCHEDULE_DATA = [
    {"id": 1, "date": "2026-03-06", "title": "NAS Equipment Review", "priority": "high", "status": "upcoming"},
    {"id": 2, "date": "2026-03-07", "title": "Predictive Maintenance Sync", "priority": "medium", "status": "upcoming"},
    {"id": 3, "date": "2026-03-10", "title": "PRL Stakeholder Briefing", "priority": "high", "status": "upcoming"},
    {"id": 4, "date": "2026-03-12", "title": "Outage Pattern Analysis", "priority": "low", "status": "upcoming"},
    {"id": 5, "date": "2026-03-14", "title": "ESU Environmental Trends Review", "priority": "medium", "status": "upcoming"},
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

REFERENCE_DOCS = [
    {"id": "cba", "label": "CBA / Bargaining Manual", "icon": "📘", "desc": "Collective Bargaining Agreement reference"},
    {"id": "hrpm", "label": "HRPM", "icon": "📗", "desc": "Human Resources Policy Manual"},
    {"id": "guides", "label": "Management Guides", "icon": "📙", "desc": "Operational management guidelines"},
    {"id": "memos", "label": "Memos", "icon": "📋", "desc": "Internal memoranda archive"},
]


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


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


@app.route("/api/references")
def api_references():
    return jsonify(REFERENCE_DOCS)


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    data = request.json
    # In production, integrate with actual email system
    return jsonify({
        "status": "sent",
        "to": data.get("to", []),
        "subject": data.get("subject", ""),
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.json
    question = data.get("question", "")
    # Simulated PRL Engine response
    response = (
        f'Decision prompt generated for: "{question}"\n\n'
        "▸ Signal analysis: scanning work orders, repeat failures, ESU trends\n"
        "▸ Risk assessment: calculating mission impact score\n"
        "▸ Recommended actions: prioritized by urgency and resource availability\n\n"
        "This is a simulated response. In production, PRL would integrate real NAS data streams."
    )
    return jsonify({"answer": response})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
