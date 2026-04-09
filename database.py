"""
PRL Engine v3 — Database Layer
SQLite persistence for schedule, emails, letters, governance, decisions, and feedback.
"""

import os
import sqlite3
import json
import logging
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("PRL_DB_PATH", os.path.join(os.path.dirname(__file__), "prl_data.db"))


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema and seed default data if empty."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schedule_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                title TEXT NOT NULL,
                priority TEXT DEFAULT 'medium',
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'upcoming',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipients TEXT DEFAULT '[]',
                subject TEXT NOT NULL,
                body TEXT DEFAULT '',
                time_label TEXT DEFAULT '',
                read INTEGER DEFAULT 0,
                sent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS letter_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT DEFAULT '',
                template_body TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS governance_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT DEFAULT 'Federal',
                status TEXT DEFAULT 'Active',
                description TEXT DEFAULT '',
                last_reviewed TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT DEFAULT '[]',
                reasoning_summary TEXT DEFAULT '',
                mode TEXT DEFAULT 'rag',
                chunks_used INTEGER DEFAULT 0,
                feedback_status TEXT DEFAULT 'pending',
                feedback_notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER,
                feedback_type TEXT DEFAULT 'approval',
                notes TEXT DEFAULT '',
                reviewer TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (decision_id) REFERENCES decisions(id)
            );
        """)

        # Seed default data if tables are empty
        if conn.execute("SELECT COUNT(*) FROM schedule_events").fetchone()[0] == 0:
            _seed_schedule(conn)
        if conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 0:
            _seed_emails(conn)
        if conn.execute("SELECT COUNT(*) FROM letter_templates").fetchone()[0] == 0:
            _seed_letters(conn)
        if conn.execute("SELECT COUNT(*) FROM governance_items").fetchone()[0] == 0:
            _seed_governance(conn)

    logger.info(f"Database initialized at {DB_PATH}")


def _seed_schedule(conn):
    events = [
        ("2026-04-10", "NAS Equipment Review", "high",
         "Quarterly review of National Airspace System equipment status, maintenance backlogs, and replacement timelines. "
         "Covers RCAG, ASR, ATCT, and VORTAC systems. Attendees include ETR leads, maintenance supervisors, and AIT coordination. "
         "Prepare equipment condition reports and any outstanding work orders for discussion.", "upcoming"),
        ("2026-04-12", "Predictive Maintenance Sync", "medium",
         "Cross-functional sync between maintenance teams and data analysts on predictive maintenance model outputs. "
         "Review failure probability scores for critical NAS infrastructure, discuss upcoming preventive actions, "
         "and align on resource allocation for Q2 maintenance windows.", "upcoming"),
        ("2026-04-15", "PRL Stakeholder Briefing", "high",
         "Brief AIT leadership and division managers on PRL Engine deployment progress, user adoption metrics, "
         "decision quality improvements, and knowledge base coverage. Present cost savings data from reduced policy "
         "interpretation time and improved decision consistency across facilities.", "upcoming"),
        ("2026-04-18", "Outage Pattern Analysis", "low",
         "Data review session analyzing Q1 outage patterns across the COMM group. Identify recurring failure modes, "
         "geographic clusters, and time-of-day trends. Output feeds into the predictive maintenance model and "
         "informs upcoming equipment refresh priorities.", "upcoming"),
        ("2026-04-20", "ESU Environmental Trends Review", "medium",
         "Environmental Systems Unit quarterly analysis of HVAC, power, and environmental control performance "
         "across technical facilities. Review temperature exceedance events, power quality incidents, and generator "
         "test results. Identify facilities requiring capital investment.", "upcoming"),
        ("2026-04-22", "BWS Union Collaboration Meeting", "high",
         "Formal collaboration session with PASS union representatives to review proposed Basic Watch Schedule changes "
         "for Q3. Covers Article 31 notification requirements, crew pairing adjustments, mid-shift transitions, "
         "and 16x7 coverage models. Union must be notified per CBA Article 31 timelines.", "upcoming"),
        ("2026-04-25", "Coverage Gap Assessment", "medium",
         "Analysis of Alternative Work Schedule coverage gaps for Q2. Review zero-coverage days identified in the "
         "current AWS cycle, evaluate overtime solicitation needs per CBA Article 34, and prepare workforce "
         "notifications. Output includes OT solicitation language and ALP clarification emails.", "upcoming"),
    ]
    conn.executemany(
        "INSERT INTO schedule_events (date, title, priority, description, status) VALUES (?, ?, ?, ?, ?)",
        events,
    )


def _seed_emails(conn):
    emails = [
        ("NAS Ops", '["ETR"]', "Outage Report — Sector 7 TRACON",
         "Priority notification: Unscheduled outage reported at Sector 7 TRACON affecting radar approach control services. "
         "Primary ASR-9 radar went offline at 0342Z. Backup systems engaged. Maintenance team dispatched. "
         "ETR coordination required for parts sourcing and estimated restoration timeline. "
         "Please review the attached incident report and provide initial impact assessment by COB.",
         "2h ago", 0, 0),
        ("ETR Division", '["Supervisor"]', "Equipment refresh timeline update",
         "The FY26 equipment refresh timeline has been updated to reflect revised delivery schedules from the vendor. "
         "Key changes: RCAG replacements moved from Q2 to Q3, new ATCT console installations on track for May. "
         "Please review the attached Gantt chart and confirm your facility's readiness dates. "
         "Any conflicts with the BWS or maintenance windows should be flagged by Friday.",
         "5h ago", 1, 0),
        ("HR", '["Supervisor"]', "Re: Staffing matrix Q2",
         "The Q2 staffing matrix has been finalized and is ready for supervisory review. Your team's allocation "
         "reflects the recent vacancy backfill for the ESS-3 position and the temporary detail to HQ. "
         "Please verify headcount accuracy, confirm any pending leave requests that affect coverage, "
         "and sign off in the HR portal by April 15th.",
         "1d ago", 1, 0),
        ("AIT Leadership", '["ETR", "Supervisor"]', "FY26 Budget Alignment — Division Priorities Due",
         "All division leads: FY26 budget alignment meeting is scheduled for April 28th. Each division must "
         "submit prioritized capital investment requests, O&M projections, and any unfunded requirements by April 22nd. "
         "Format: use the standard budget template (attached). Include justification narratives for any item over $50K. "
         "PRL-generated cost analyses are acceptable as supporting documentation.",
         "2d ago", 1, 0),
        ("PASS Union Rep", '["Supervisor", "HR"]', "Article 31 — Schedule Change Notice",
         "This constitutes formal notice under PASS CBA Article 31 regarding proposed changes to the Basic Watch Schedule "
         "for the COMM Group effective Q3 FY26. The union requests a collaboration meeting within 15 calendar days "
         "as stipulated in the agreement. Please provide available dates and the proposed schedule framework "
         "for review prior to the meeting. All supporting documentation (coverage analysis, AWS evaluation, "
         "manning calculations) should be provided at least 5 business days in advance.",
         "3d ago", 0, 0),
    ]
    conn.executemany(
        "INSERT INTO emails (sender, recipients, subject, body, time_label, read, sent) VALUES (?, ?, ?, ?, ?, ?, ?)",
        emails,
    )


def _seed_letters(conn):
    letters = [
        ("Letter of Counseling", "Disciplinary",
         "First-level corrective action used to formally document a discussion with an employee about performance "
         "deficiencies or minor conduct issues. Not a formal disciplinary action under 5 USC 7512 but creates a "
         "written record. Typically references specific incidents, expectations, and consequences of continued issues. "
         "Can be grieved under CBA Article 10.",
         "SUBJECT: Letter of Counseling\n\nDear [Employee Name],\n\nThis letter serves to document our discussion "
         "on [date] regarding [specific issue]. As your supervisor, I want to ensure you understand the expectations "
         "for your position...\n\n[Detail specific incidents, dates, and policy references]\n\nExpected corrective "
         "action: [specific expectations]\n\nConsequences of continued issues: [next steps]\n\nSincerely,\n[Manager Name]"),
        ("Letter of Reprimand", "Disciplinary",
         "Formal disciplinary action under 5 USC 7512 documenting specific policy violations with citations to "
         "applicable regulations, HRPM sections, and CBA articles. Must include specific charges, evidence summary, "
         "employee's right to respond (typically 10 business days), and appeal rights. HR review required before issuance. "
         "Becomes part of the Official Personnel File (OPF) for up to 2 years.",
         "SUBJECT: Letter of Reprimand\n\nDear [Employee Name],\n\nThis letter constitutes a formal Letter of Reprimand "
         "for [specific charge(s)].\n\nCharge: [Detailed charge with dates, evidence, and policy citations]\n\n"
         "This action is taken pursuant to [HRPM reference]. You have the right to respond to this action within "
         "[10] business days...\n\nSincerely,\n[Manager Name]\n\ncc: HR, OPF"),
        ("Commendation Letter", "Recognition",
         "Formal recognition letter for exceptional performance, initiative, or contribution to mission objectives. "
         "Used to document outstanding work that goes beyond normal duties. Can reference specific projects, "
         "measurable outcomes, or leadership during critical operational periods. Appropriate for award nominations, "
         "performance documentation, or morale recognition.",
         "SUBJECT: Letter of Commendation\n\nDear [Employee Name],\n\nI am writing to formally recognize your "
         "exceptional performance in [specific area/project]. Your [specific contributions] directly resulted in "
         "[measurable outcomes]...\n\nThis letter will be placed in your Employee Performance File.\n\nSincerely,\n[Manager Name]"),
        ("Proposal to Remove", "Disciplinary",
         "Most severe disciplinary action — formal proposal to remove the employee from federal service. Requires "
         "thorough documentation of progressive discipline history, specific charges with evidence, and legal review. "
         "Employee has 30 calendar days to respond. Must be reviewed by HR, legal, and deciding official (different "
         "from proposing official). Subject to MSPB appeal and CBA grievance/arbitration procedures.",
         "SUBJECT: Proposal to Remove\n\nDear [Employee Name],\n\nThis is to advise you that I am proposing your "
         "removal from your position as [title] with the Federal Aviation Administration, effective [date].\n\n"
         "The reasons for this proposed action are:\n\nCharge 1: [Detailed charge]\nCharge 2: [Detailed charge]\n\n"
         "You have the right to respond to this proposal within 30 calendar days..."),
        ("Last Chance Agreement", "Settlement",
         "Settlement document offering the employee a final opportunity to retain employment under strict conditions. "
         "Typically used to resolve pending removal actions. Includes specific behavioral requirements, monitoring "
         "period (usually 12-24 months), and automatic consequence if terms are violated. Must be reviewed by legal "
         "and HR. Employee should be encouraged to seek union representation before signing.",
         "LAST CHANCE AGREEMENT\n\nBetween: [Agency] and [Employee Name]\n\nWhereas: [Background of the pending action]\n\n"
         "Terms:\n1. [Specific behavioral requirements]\n2. Monitoring period: [duration]\n3. Consequence of violation: "
         "[automatic removal/demotion]\n\nAcknowledgment: The employee acknowledges...\n\nSignatures:\n[Employee] [Manager] [HR] [Union Rep]"),
        ("Leave Restriction Letter", "Administrative",
         "Administrative notice imposing restrictions on an employee's leave usage due to a pattern of abuse or "
         "excessive unscheduled absences. Must document the specific pattern (dates, frequency), cite applicable "
         "leave policies (HRPM LWS-8.14, CBA Article 35), and define the restrictions and their duration. "
         "Employee retains all leave entitlements but may be required to provide medical documentation or advance notice. "
         "Grievable under the CBA.",
         "SUBJECT: Leave Restriction Notice\n\nDear [Employee Name],\n\nThis letter notifies you that effective [date], "
         "your leave usage will be subject to the following restrictions due to [documented pattern of abuse]:\n\n"
         "1. [Specific restrictions]\n2. [Documentation requirements]\n3. Duration: [period]\n\n"
         "This action is taken pursuant to HRPM LWS-8.14 and CBA Article 35...\n\nSincerely,\n[Manager Name]"),
        ("OT Solicitation Notice", "Scheduling",
         "Formal overtime solicitation document per CBA Article 34 requirements. Must follow the contractual solicitation "
         "order (qualified volunteers by seniority, then mandatory assignment by inverse seniority). Document must "
         "include the specific dates, hours, reason for overtime need, and response deadline. Essential for maintaining "
         "compliance and defending against grievances related to overtime distribution.",
         "OVERTIME SOLICITATION NOTICE\n\nDate: [date]\nCoverage Period: [dates/shifts]\nReason: [operational need]\n\n"
         "Volunteers are solicited in accordance with CBA Article 34, Section [X]. Please indicate your availability "
         "by [deadline].\n\n[Seniority-ordered employee list with response fields]\n\n"
         "Note: If insufficient volunteers, mandatory assignment will proceed by inverse seniority per Article 34."),
        ("AWOL Notice", "Disciplinary",
         "Official notice to an employee that their absence has been determined to be unauthorized (Absent Without "
         "Official Leave). Documents the specific dates of absence, attempts to contact the employee, and the "
         "determination rationale. Typically the first step before potential disciplinary action. Employee must "
         "be given opportunity to provide justification or retroactive leave requests. Cite HRPM and CBA provisions "
         "for leave request procedures.",
         "SUBJECT: Notice of AWOL Determination\n\nDear [Employee Name],\n\nThis letter notifies you that your "
         "absence on [date(s)] has been charged as Absent Without Official Leave (AWOL).\n\n"
         "Basis: [No leave request on file / Failure to follow call-in procedures / etc.]\n"
         "Contact attempts: [documented attempts to reach employee]\n\n"
         "You may provide documentation to support a retroactive leave request within [timeframe]...\n\nSincerely,\n[Manager Name]"),
        ("Union Collaboration Memo", "Labor Relations",
         "Formal memorandum documenting union collaboration on matters requiring negotiation or consultation under "
         "the CBA. Used for schedule changes (Article 31), working condition modifications, or policy implementations "
         "affecting bargaining unit employees. Must document the subject, proposed changes, union notification date, "
         "collaboration meeting dates, and outcomes. Critical for demonstrating good-faith bargaining compliance.",
         "MEMORANDUM\n\nTO: PASS Local [Number]\nFROM: [Manager Name/Title]\nSUBJECT: Union Collaboration — [Topic]\n"
         "DATE: [date]\n\nPurpose: This memorandum documents the collaboration process for [proposed change].\n\n"
         "Background: [Context for the change]\nProposed Action: [Specific changes]\n"
         "Notification Date: [When union was notified]\nCollaboration Meeting(s): [Dates and outcomes]\n"
         "Resolution: [Agreed-upon approach or remaining disagreements]"),
        ("Incident Executive Summary", "Reporting",
         "Concise executive-level summary of an operational incident for leadership reporting. Covers the incident "
         "timeline, impact assessment (service disruption, safety implications, NAS impact), root cause (if known), "
         "immediate corrective actions taken, and follow-up items. Used for upward reporting to AIT leadership, "
         "district management, or headquarters. Should be factual, timeline-based, and free of speculation.",
         "INCIDENT EXECUTIVE SUMMARY\n\nDate/Time: [incident timestamp]\nLocation: [facility/system]\n"
         "Systems Affected: [NAS systems impacted]\nService Impact: [duration and scope of disruption]\n\n"
         "TIMELINE:\n[Chronological sequence of events]\n\nROOT CAUSE: [Determined/Under investigation]\n"
         "CORRECTIVE ACTIONS: [Actions taken]\nFOLLOW-UP: [Remaining items]\n\nPrepared by: [Name/Title]"),
    ]
    conn.executemany(
        "INSERT INTO letter_templates (title, type, description, template_body) VALUES (?, ?, ?, ?)",
        letters,
    )


def _seed_governance(conn):
    items = [
        ("OMB Circular A-130", "Federal", "Active",
         "Establishes policy for the planning, budgeting, governance, acquisition, and management of federal "
         "information, personnel, equipment, funds, IT resources, and supporting infrastructure. Requires agencies "
         "to manage information as a strategic resource and protect PII. Directly governs how PRL handles policy documents."),
        ("FAA Order 1370.121", "FAA/DOT", "Active",
         "Defines the FAA's Information Security and Privacy Program including system categorization, access controls, "
         "incident response, and continuous monitoring requirements. All FAA IT systems including PRL must comply. "
         "Governs data handling, user authentication, and audit trail requirements for federal information systems."),
        ("Executive Order on AI", "Federal", "Under Review",
         "Executive Order 14110 on Safe, Secure, and Trustworthy Artificial Intelligence. Establishes requirements "
         "for federal agency use of AI including risk assessments, transparency, human oversight, and civil rights "
         "protections. PRL's human-in-the-loop governance model and visible reasoning chain align with these requirements."),
        ("DOT Data Governance Policy", "FAA/DOT", "Active",
         "Department of Transportation framework for data quality, integrity, accessibility, and lifecycle management. "
         "Applies to all DOT modal administrations including FAA. Governs how PRL's knowledge base documents are "
         "cataloged, version-controlled, and retired when superseded by updated policy."),
        ("NIST AI RMF", "Regulatory", "Reference",
         "NIST AI Risk Management Framework (AI 100-1) providing voluntary guidance for managing AI risks. "
         "Organized around four functions: Govern, Map, Measure, Manage. PRL's architecture maps to this framework: "
         "governance via human-in-the-loop approval, measurement via the decision audit trail, and management via "
         "the institutional memory feedback loop."),
        ("PASS CBA", "Labor Relations", "Active",
         "Collective Bargaining Agreement between FAA and the Professional Aviation Safety Specialists (PASS) union. "
         "Governs working conditions, scheduling, overtime, leave, discipline, and grievance procedures for bargaining "
         "unit employees. Key articles for PRL: Article 31 (Basic Watch Schedule), Article 34 (Overtime), "
         "Article 35 (Leave), Article 10 (Grievance Procedure). Primary source for labor relations queries."),
        ("HRPM LWS-8.14", "HR Policy", "Active",
         "FAA Human Resources Policy Manual — Leave and Work Schedules chapter. Covers annual leave, sick leave, "
         "LWOP, FMLA, AWS, credit hours, compensatory time, and religious observance leave. Defines approval authorities, "
         "documentation requirements, and restrictions. One of the most frequently referenced sources in PRL queries. "
         "Must be read alongside the CBA for bargaining unit employees."),
        ("FAA Order 3120.4", "FAA/DOT", "Active",
         "FAA Technical Operations Safety Management System (SMS) order. Establishes safety management requirements "
         "for ATO Technical Operations including hazard identification, risk assessment, safety assurance, and "
         "safety promotion. Relevant to PRL when policy questions touch on maintenance decisions, staffing levels "
         "that affect safety, or operational procedures with safety implications."),
        ("FISMA Compliance", "Security", "Active",
         "Federal Information Security Modernization Act of 2014 requirements for federal information systems. "
         "Mandates risk-based security programs, continuous monitoring, incident reporting, and annual assessments. "
         "PRL must maintain an Authority to Operate (ATO) and comply with NIST 800-53 security controls. "
         "Audit trail and access control features support FISMA compliance."),
        ("FedRAMP Authorization", "Security", "In Progress",
         "Federal Risk and Authorization Management Program — standardized approach to security assessment for "
         "cloud products used by federal agencies. PRL's Railway deployment requires FedRAMP authorization for "
         "production federal use. Currently documenting the System Security Plan (SSP), completing the security "
         "assessment, and preparing for the authorization package submission."),
    ]
    conn.executemany(
        "INSERT INTO governance_items (title, category, status, description) VALUES (?, ?, ?, ?)",
        items,
    )


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------

# --- Schedule ---
def get_schedule():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM schedule_events ORDER BY date ASC").fetchall()
        return [dict(r) for r in rows]

def create_schedule_event(data):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO schedule_events (date, title, priority, description, status) VALUES (?, ?, ?, ?, ?)",
            (data["date"], data["title"], data.get("priority", "medium"), data.get("description", ""), data.get("status", "upcoming")),
        )
        return {"status": "created"}

def update_schedule_event(event_id, data):
    with get_db() as conn:
        conn.execute(
            "UPDATE schedule_events SET date=?, title=?, priority=?, description=?, status=?, updated_at=datetime('now') WHERE id=?",
            (data["date"], data["title"], data.get("priority", "medium"), data.get("description", ""), data.get("status", "upcoming"), event_id),
        )
        return {"status": "updated"}

def delete_schedule_event(event_id):
    with get_db() as conn:
        conn.execute("DELETE FROM schedule_events WHERE id=?", (event_id,))
        return {"status": "deleted"}


# --- Emails ---
def get_emails(sent=False):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM emails WHERE sent=? ORDER BY created_at DESC", (1 if sent else 0,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["recipients"] = json.loads(d["recipients"]) if d["recipients"] else []
            d["read"] = bool(d["read"])
            d["sent"] = bool(d["sent"])
            result.append(d)
        return result

def create_email(data):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO emails (sender, recipients, subject, body, time_label, read, sent) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("PRL User", json.dumps(data.get("to", [])), data.get("subject", ""), data.get("body", ""), "just now", 1, 1),
        )
        return {"status": "sent", "timestamp": datetime.utcnow().isoformat()}

def mark_email_read(email_id):
    with get_db() as conn:
        conn.execute("UPDATE emails SET read=1 WHERE id=?", (email_id,))
        return {"status": "updated"}


# --- Letters ---
def get_letters():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM letter_templates ORDER BY type, title").fetchall()
        return [dict(r) for r in rows]

def create_letter(data):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO letter_templates (title, type, description, template_body) VALUES (?, ?, ?, ?)",
            (data["title"], data["type"], data.get("description", ""), data.get("template_body", "")),
        )
        return {"status": "created"}


# --- Governance ---
def get_governance():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM governance_items ORDER BY category, title").fetchall()
        return [dict(r) for r in rows]

def create_governance_item(data):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO governance_items (title, category, status, description) VALUES (?, ?, ?, ?)",
            (data["title"], data.get("category", "Federal"), data.get("status", "Active"), data.get("description", "")),
        )
        return {"status": "created"}

def update_governance_item(item_id, data):
    with get_db() as conn:
        conn.execute(
            "UPDATE governance_items SET title=?, category=?, status=?, description=?, updated_at=datetime('now') WHERE id=?",
            (data["title"], data.get("category", "Federal"), data.get("status", "Active"), data.get("description", ""), item_id),
        )
        return {"status": "updated"}


# --- Decisions (Audit Trail) ---
def save_decision(question, answer, sources, reasoning_summary, mode, chunks_used):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO decisions (question, answer, sources, reasoning_summary, mode, chunks_used) VALUES (?, ?, ?, ?, ?, ?)",
            (question, answer, json.dumps(sources), reasoning_summary, mode, chunks_used),
        )
        return cursor.lastrowid

def get_decisions(limit=50):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["sources"] = json.loads(d["sources"]) if d["sources"] else []
            result.append(d)
        return result

def update_decision_feedback(decision_id, status, notes=""):
    with get_db() as conn:
        conn.execute(
            "UPDATE decisions SET feedback_status=?, feedback_notes=?, reviewed_at=datetime('now') WHERE id=?",
            (status, notes, decision_id),
        )
        return {"status": "updated"}


# --- Feedback (Institutional Memory) ---
def save_feedback(decision_id, feedback_type, notes, reviewer=""):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO feedback (decision_id, feedback_type, notes, reviewer) VALUES (?, ?, ?, ?)",
            (decision_id, feedback_type, notes, reviewer),
        )
        # Also update the decision record
        conn.execute(
            "UPDATE decisions SET feedback_status=?, feedback_notes=?, reviewed_at=datetime('now') WHERE id=?",
            (feedback_type, notes, decision_id),
        )
        return {"status": "saved"}

def get_feedback(limit=100):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT f.*, d.question, d.answer
            FROM feedback f
            LEFT JOIN decisions d ON f.decision_id = d.id
            ORDER BY f.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# --- Stats ---
def get_dashboard_stats():
    with get_db() as conn:
        schedule_count = conn.execute("SELECT COUNT(*) FROM schedule_events WHERE status='upcoming'").fetchone()[0]
        unread_emails = conn.execute("SELECT COUNT(*) FROM emails WHERE read=0 AND sent=0").fetchone()[0]
        total_decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        approved_decisions = conn.execute("SELECT COUNT(*) FROM decisions WHERE feedback_status='approved'").fetchone()[0]
        governance_active = conn.execute("SELECT COUNT(*) FROM governance_items WHERE status='Active'").fetchone()[0]
        return {
            "upcoming_events": schedule_count,
            "unread_emails": unread_emails,
            "total_decisions": total_decisions,
            "approved_decisions": approved_decisions,
            "governance_active": governance_active,
            "approval_rate": round(approved_decisions / total_decisions * 100, 1) if total_decisions > 0 else 0,
        }
