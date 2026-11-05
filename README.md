# CYVANTA

CYVANTA is a security operations and intelligence platform under active development. Its direction combines Red Team, Blue Team, and cyber-intelligence workflows with authorization controls, human review, auditability, and operational safeguards.

> **Development status:** Engineering foundation. The current implementation is an early-stage application, not a production-ready autonomous security platform. Some operational workflows are planning/record-management only; do not assume that creating a mission or queue record runs a scanner or performs a security action.

## Current implementation

### Backend
- Python and FastAPI
- SQLAlchemy 2.x
- SQLite for the current local development database
- JWT-based authentication
- Argon2 password hashing
- Organization membership and reviewer invitations
- Asset registration and authorization records
- Mission and action proposal workflows
- Execution records, event history, and emergency-stop controls
- Automated tests with pytest

### Frontend
- React 19 and Vite
- JavaScript / JSX
- React Router
- Three.js with React Three Fiber and Drei
- Framer Motion and GSAP
- Recharts and XYFlow

### Local demonstration environment
The `demo-lab/` folder contains a harmless local web application used to validate CYVANTA workflows. It binds only to `127.0.0.1:8765` and is not exposed to the LAN or public internet. It does not scan, exploit, collect credentials, or control other systems.

## Security and engineering principles

- Work only with assets for which authorization has been established.
- Apply least-privilege access and role-based permissions.
- Keep authorization review separate from the requester; users cannot approve their own requests.
- Require human approval for controlled actions.
- Preserve audit and execution history.
- Keep emergency-stop controls restricted to authorized roles.
- Treat test/demo assets as local and explicitly scoped.
- Do not represent planning records as completed security operations.

## Repository layout

```text
CYVANTA/
â”œâ”€â”€ backend/       FastAPI application, database models, and tests
â”œâ”€â”€ frontend/      React + Vite application
â”œâ”€â”€ demo-lab/      Loopback-only local demonstration application
â”œâ”€â”€ .env.example   Environment configuration template
â””â”€â”€ README.md
```

Local virtual environments, dependency folders, build output, databases, environment files, and recovery backups are intentionally excluded from version control.

## Local development

### Backend

Open PowerShell in the repository root:

```powershell
cd backend

# Create the virtual environment if it does not already exist
python -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
python -m pip install -r requirements.txt

# Configure local environment values using the root/backend environment template
# Do not commit real secrets or local .env files.

# Start the API
python -m uvicorn app.main:app --reload
```

The local API base URL is `http://127.0.0.1:8000`.

Health check:

`http://127.0.0.1:8000/api/v1/health`

### Frontend

Open a second PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

Vite prints the local development URL in the terminal.

### Local Demo Lab

Open another PowerShell window:

```powershell
cd demo-lab
python demo_app.py
```

Open `http://127.0.0.1:8765` in your browser. Health endpoint: `http://127.0.0.1:8765/health`.

Stop the Demo Lab with `Ctrl+C`.

## Tests

From the repository root:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests -q
```

The latest recorded backend regression run in this development checkpoint completed with **136 passed**. Re-run the suite after making changes; this number is a historical checkpoint, not a guarantee about future revisions.

## Current limitations

- SQLite is the current local development database; the README does not claim PostgreSQL deployment support.
- No email delivery provider is configured for organization invitations. Development mode exposes a one-time invitation token for secure manual handoff.
- Mission planning and queue records do not, by themselves, execute scans or other security operations.
- The current frontend and backend are under active development and require further security review, integration testing, deployment hardening, and operational validation before production use.

## Project direction

CYVANTA is being developed around three complementary disciplines:

1. **Red Team** â€” authorized offensive-security assessment workflows.
2. **Blue Team** â€” defensive monitoring and response workflows.
3. **Black Team** â€” cyber-intelligence and investigation workflows.

The long-term direction is to connect these workflows through controlled authorization, evidence, human oversight, and auditable operations. Planned capabilities should be treated as roadmap items until implemented and tested.
