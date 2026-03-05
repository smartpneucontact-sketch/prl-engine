# PRL Engine — Predictive Readiness Loop

**NAS Mission Readiness Engine** — A strategic innovation tool for predictive maintenance and decision support in mission-critical environments.

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`

## Deploy to Railway

### Option 1: Railway CLI
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Deploy
railway up
```

### Option 2: GitHub Integration
1. Push this repo to GitHub
2. Go to [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo**
3. Select the repo — Railway auto-detects the Python app
4. Click **Deploy** — Railway assigns a public URL automatically

### Option 3: Railway Dashboard
1. Go to [railway.com](https://railway.com) → **New Project** → **Empty Project**
2. Add a service → **Deploy from GitHub** or drag-and-drop the project folder
3. Railway will auto-detect the `Procfile` and deploy

## Project Structure
```
prl-engine/
├── app.py              # Flask app with API routes
├── templates/
│   └── index.html      # Full PRL interface
├── static/             # Static assets (if needed)
├── requirements.txt    # Python dependencies
├── Procfile            # Process command for deployment
├── railway.json        # Railway configuration
├── nixpacks.toml       # Build configuration
└── .gitignore
```

## Features
- **Schedule** — NAS event tracking with priority badges
- **Email** — Inbox + compose with recipient routing (ETR, HR, Supervisor, AIT Leadership)
- **Letters** — Template library for official correspondence
- **Ask Questions** — PRL decision engine with signal analysis
- **Governance** — Regulatory controls tracking (OMB, FAA, NIST)
- **Reference Docs** — CBA, HRPM, Management Guides, Memos

---
*"We will not wait for failure to teach us."*
