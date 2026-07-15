# Backend

FastAPI backend for Burned Area Explorer.

Run:

```bash
uv sync --index-url https://pypi.org/simple
uv run python scripts/generate_demo_data.py
uv run uvicorn app.main:app --reload --port 8000
```

The backend includes a deterministic workflow runner. It reads workflow definitions from `../workflow_skills/*/workflow.yaml` and maps step tools to Python functions in `app/workflows/tools.py`.
