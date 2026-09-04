# Kite

Personal PWA for staying current on tech and tracking dependency risk. React frontend, FastAPI backend, Supabase for Postgres and Auth.

## Local development

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
copy .env.example .env   # then fill in secrets
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm ci
copy .env.example .env   # then fill in VITE_SUPABASE_* 
npm run dev
```

Frontend: http://localhost:5173 · API: http://localhost:8000/health

## Deploy

This repo is set up for a split deploy:

| Piece | Host | Why |
|---|---|---|
| React PWA | Vercel | `cd frontend && npx vercel --prod` |
| FastAPI | Fly.io / Render (Docker) | always-on Python process |
| Postgres + Auth | Supabase | already used by the app |

Step-by-step: [docs/deploy.md](docs/deploy.md)

## Layout

```
backend/     FastAPI, agents, migrations
frontend/    Vite + React PWA
docs/        product spec and deploy runbook
```
