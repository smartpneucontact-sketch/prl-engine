# PRL Engine v3.0 — Policy Reasoning Layer

**Five-Layer Decision Intelligence Engine** — RAG-powered policy reasoning for operational managers in policy-dense federal agencies.

Built by Ronald C. Owens Jr. | CJD Global Defense Contracting LLC

## Architecture

```
Manager Query → Query Processor → Vector Search (ChromaDB) → Chain-of-Thought Reasoning (Claude) → Structured Governance-Ready Output
```

### Five-Layer RAG Architecture

| Layer | Function |
|-------|----------|
| **Layer 1 — Ingestion Engine** | Policy documents processed, chunked, and stored in vector database with source tagging |
| **Layer 2 — Query Processor** | Intent interpretation; clarifying questions when ambiguous |
| **Layer 3 — Retrieval Engine** | Semantic search; ranked citations with source attribution |
| **Layer 4 — Reasoning Engine** | Chain-of-thought logic; visible reasoning pathway; edge case flagging |
| **Layer 5 — Output Generator** | Plain language answer + reasoning summary + citations + governance artifact |

### Features

| Tab | Function |
|-----|----------|
| **Dashboard** | Command center with key metrics and quick actions |
| **Ask PRL** | Five-layer policy reasoning engine with citations and feedback loop |
| **Knowledge Base** | Upload, ingest, and manage policy documents |
| **Schedule** | Operational event tracking with CRUD |
| **Email** | Compose with routing (ETR, HR, Supervisor, AIT Leadership, Union Rep, Legal) |
| **Letters** | Template library for official correspondence (10 types) |
| **Governance** | Regulatory and compliance framework tracking |
| **Audit Trail** | Decision history with approval/flagging feedback loop |

## What's New in v3

- **Five-Layer RAG Architecture** — Query processing, intent classification, chain-of-thought reasoning
- **Institutional Memory** — Decision audit trail with approval/flagging/rejection feedback loop
- **SQLite Persistence** — All data (schedule, emails, letters, governance, decisions) persisted to database
- **Professional UI** — Gold/navy federal-grade design matching CJD Global branding
- **Dashboard** — Command center with real-time metrics
- **Expanded Letter Templates** — 10 governance-ready templates across 6 categories
- **Enhanced Governance** — 10 regulatory items across 6 categories
- **Structured Output** — Every PRL response includes: Guidance, Answer, Authority, Risks, Recommended Action, Reasoning Chain

## Setup

### Local Development

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

Visit `http://localhost:5000`

### Deploy to Railway

1. Push to GitHub
2. Railway → New Project → Deploy from GitHub
3. Add `ANTHROPIC_API_KEY` in Variables
4. Settings → Networking → Generate Domain

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key for reasoning |
| `PRL_MODEL` | No | `claude-sonnet-4-20250514` | Claude model to use |
| `PRL_CHUNK_SIZE` | No | `800` | Document chunk size (chars) |
| `PRL_TOP_K` | No | `8` | Number of chunks to retrieve |
| `PRL_DB_PATH` | No | `./prl_data.db` | SQLite database path |
| `PORT` | No | `5000` | Server port |

## Tech Stack

- **Backend**: Python 3.11 / Flask
- **Database**: SQLite (persistent)
- **Vector Store**: ChromaDB (embedded, persistent)
- **LLM**: Anthropic Claude (via API)
- **Document Processing**: PyPDF2, python-docx
- **Deployment**: Railway / Nixpacks / Gunicorn

---

*"We will not wait for failure to teach us."*

**PRL Engine v3.0** — CJD Global Defense Contracting LLC
