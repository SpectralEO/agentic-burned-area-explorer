# Custom composite tiler

Local FastAPI tile service for rendering STAC COG assets as MapLibre raster tiles.

It supports:

- single visual/TCI-like RGB assets through `visual=<href>`;
- three-band composites through `r=<href>&g=<href>&b=<href>`;
- optional fire-front blending through `blend_r`, `blend_g`, `blend_b`, and `blend_weight`.

Run locally:

```bash
cd tiler
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8001
```

Or through Docker from the repo root:

```bash
docker compose up --build tiler
```

Health check:

```bash
curl http://localhost:8001/health
```
