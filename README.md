# PRL Engine v2.0 — Policy Reasoning Layer

**Decision Intelligence Engine** — RAG-powered policy decision support for operational managers in policy-dense organizations.

## What It Does

PRL is a **Policy GPS** — managers drive, PRL navigates. It reasons across multiple overlapping policy frameworks (CBA, HRPM, agency orders, management guides, memos) and returns cited, structured, defensible guidance in seconds.

### Architecture

```
Manager Query → Vector Search (ChromaDB) → Policy Retrieval → Claude Reasoning → Cited Answer
```

### Features

| Tab | Function |
|-----|----------|
| **Schedule** | Operational event tracking |
| **Email** | Compose with routing (ETR, HR, Supervisor, AIT Leadership) |
| **Letters** | Template library for official correspondence |
| **Ask PRL** | RAG-powered policy reasoning engine with citations |
| **Knowledge Base** | Upload, ingest, and manage policy documents |
| **Governance** | Regulatory controls tracking |

## Setup

### 1. Local Development

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

Visit `http://localhost:5000`

### 2. Deploy to Railway

**Push to GitHub:**
```bash
git init && git add . && git commit -m "PRL Engine v2.0"
git remote add origin https://github.com/YOUR_ORG/prl-engine.git
git push -u origin main
```

**On Railway:**
1. Go to [railway.com](https://railway.com) → New Project → Deploy from GitHub
2. Select the repo
3. Go to **Variables** tab and add:
   - `ANTHROPIC_API_KEY` = your Anthropic API key
4. Go to **Settings** → **Networking** → **Generate Domain**

### 3. Add Your API Key

The PRL Engine uses Claude for policy reasoning. You need an Anthropic API key:

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Add it as `ANTHROPIC_API_KEY` in Railway Variables

Without the key, the app runs fine but Ask PRL will show a setup message instead of reasoning.

## Usage

1. **Upload policy documents** via the Knowledge Base tab (PDF, DOCX, TXT)
2. **Ask questions** in the Ask PRL tab — the engine retrieves relevant sections and reasons across them
3. **Get cited answers** with source documents, approval authority, conditions, and risks

### Example Queries

- "Can a technician take LWOP after sick leave exhaustion?"
- "What are the fatigue rules under Article 34?"
- "Who has approval authority for schedule changes under the CBA?"
- "What documentation is required for an FMLA request?"

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key for reasoning |
| `PRL_MODEL` | No | `claude-sonnet-4-20250514` | Claude model to use |
| `PRL_CHUNK_SIZE` | No | `800` | Document chunk size (chars) |
| `PRL_TOP_K` | No | `8` | Number of chunks to retrieve |
| `PORT` | No | `5000` | Server port |

## Tech Stack

- **Backend**: Python / Flask
- **Vector Store**: ChromaDB (embedded, persistent)
- **LLM**: Anthropic Claude (via API)
- **Document Processing**: PyPDF2, python-docx
- **Deployment**: Railway / Nixpacks

---

*"We will not wait for failure to teach us."*

**PRL Engine** — CJD Global · MIT Organizational Transformation
