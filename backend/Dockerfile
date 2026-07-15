FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml backend/README.md ./
RUN pip install --no-cache-dir -e .
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY workflow_skills ./workflow_skills
RUN python scripts/generate_demo_data.py
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
