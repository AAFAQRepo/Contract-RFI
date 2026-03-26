# Contract RFI — Legal AI Platform

## Project Structure

```
Contract_RFI/
├── docker-compose.yml       # Infrastructure services
├── .env                     # Environment configuration
├── backend/                 # FastAPI backend
│   ├── api/                 # REST API endpoints
│   ├── core/                # Config, database, service clients
│   ├── models/              # SQLAlchemy ORM models
│   ├── services/            # Business logic services
│   ├── workers/             # Celery async workers
│   └── alembic/             # Database migrations
├── frontend/                # React + Vite frontend
└── Plans/                   # Architecture & design docs
```

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Setup backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

# 3. Start backend
uvicorn api.main:app --reload --port 8080

# 4. Start frontend
cd frontend
npm install
npm run dev
```
