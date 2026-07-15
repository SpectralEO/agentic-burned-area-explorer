# Burned Area Explorer

Burned Area Explorer is an agent-assisted web application for exploring burned-area activity in Greece. It combines a React map interface, a FastAPI backend, deterministic geospatial tools, compact BA300-derived analytics data, and a local raster tiler for STAC imagery.

The app uses an agentic workflow layer to turn natural-language prompts into map updates, analytics summaries, contextual overlays, and exportable finding briefs. Prompts are routed to known workflows that call explicit tools for burned-area summaries, cluster selection, optical imagery lookup, land-cover context, exposure context, drought context, aerosol context, and brief generation.

## What Is Included

- `frontend/`: React, TypeScript, Vite, MapLibre, and the interactive burned-area exploration UI.
- `backend/`: FastAPI, SQLite state, workflow routing, BA300 analytics contracts, STAC search, report export, and deterministic workflow tools.
- `tiler/`: FastAPI service that renders STAC COG assets as tiles and static PNG previews.
- `workflow_skills/`: Runtime workflow definitions used by the app.
- `backend/app/data/demo/`: Small bundled demo fixtures.
- `backend/app/data/real/`: Compact derived BA300 metadata and monthly statistics. Raw downloads are intentionally excluded.
- `docker-compose.yml`: One-command local runtime for frontend, backend, and tiler.

Development-assistant files, local editor roles, generated caches, virtual environments, raw raster downloads, local databases, and build artifacts are not part of this package.

## Agentic Workflow Layer

Burned Area Explorer includes a lightweight agentic workflow layer. User prompts are matched to workflow intents, run through deterministic tools, and returned as structured finding cards, map layers, charts, or report-ready summaries. This keeps the experience conversational while keeping the analysis steps clear and repeatable.

## Quick Start With Docker Compose

Install Docker Desktop or a compatible Docker Compose runtime, then run:

```bash
cp .env.example .env
docker compose up --build
```

Open the app at:

```text
http://localhost:5173
```

Useful service URLs:

```text
Frontend: http://localhost:5173
Backend API docs: http://localhost:8000/docs
Tiler API docs: http://localhost:8001/docs
```

## Manual Development Setup

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Tiler:

```bash
cd tiler
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8001
```

## Prototype Flow

1. Start the app and wait for Burned Area Explorer to load the default analysis.
2. Ask: `How much burned in Greece in 2025?`
3. Use `Show largest clusters` to load the cluster layer.
4. Select a cluster on the map.
5. Request `Sentinel-2 false colour` or another optical imagery action.
6. Add land-cover, drought, aerosol, or exposure context as needed.
7. Add selected finding cards to the brief.
8. Create a Markdown or PDF brief from the selected cards.

## Data Notes

The package includes compact derived BA300 files so the prototype has useful local analytics without shipping large raw products. Real STAC imagery lookup uses public STAC endpoints and therefore needs network access. CDSE credentials are optional and are only needed if you want to sync or preprocess additional BA300 products.

Put credentials in `.env` or `backend/.env`; do not place credentials in frontend variables.

## Documentation

- [Architecture](docs/architecture.md)
- [Docker and configuration](docs/docker.md)

## Verification

Run these checks before publishing a changed copy:

```bash
python -m compileall backend/app tiler/app
cd frontend && npm run build
cd ../backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run pytest
```
