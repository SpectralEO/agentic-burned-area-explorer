# Architecture

Burned Area Explorer has three runtime services.

The frontend is a React and MapLibre application. It owns the user interface, map interactions, finding-card drawer, chart display, imagery layer controls, and report modal.

The backend is a FastAPI service. It stores investigation state in SQLite, routes prompts to workflow definitions, runs deterministic tools, searches STAC catalogues, exposes BA300 analytics endpoints, and generates Markdown and PDF briefs.

The tiler is a separate FastAPI service. It renders Cloud-Optimized GeoTIFF assets for map tiles and static PNG previews. Keeping raster rendering out of the backend keeps the API focused on state, workflow execution, and metadata.

The `workflow_skills/` directory contains runtime workflow definitions. These are product workflows, not development roles. Each workflow lists the context it needs, the tools it calls, and the follow-up actions it can suggest.

## Request Flow

1. The browser creates or loads an investigation through the backend.
2. A prompt or button action is sent to the backend.
3. The backend rule-based router selects a workflow.
4. The workflow runner calls deterministic tools.
5. New finding cards are stored in SQLite.
6. The frontend refreshes findings and map layers.
7. Report export uses selected finding cards and tiler-generated preview images.

## Services

```text
frontend  -> http://localhost:5173
backend   -> http://localhost:8000/api
tiler     -> http://localhost:8001
```

Inside Docker Compose, the backend reaches the tiler through `http://tiler:8000`.
