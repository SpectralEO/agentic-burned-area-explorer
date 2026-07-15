# Docker And Configuration

Docker Compose starts the full prototype:

```bash
cp .env.example .env
docker compose up --build
```

The backend stores runtime state in `backend/app/data/investigations.sqlite`. That file is ignored by Git.

The tiler stores PNG tile cache files in `tiler-cache/`. That directory is ignored by Git.

Important environment variables:

```env
WEA_STAC_MODE=real
WEA_STAC_API_URL=https://earth-search.aws.element84.com/v1
WEA_IMAGERY_RENDER_MODE=tiler
WEA_TILER_PUBLIC_BASE=http://localhost:8001
WEA_TILER_INTERNAL_BASE=http://tiler:8000
WEA_API_PUBLIC_BASE=http://localhost:8000/api
WEA_WORKFLOW_SKILLS_DIR=/app/workflow_skills
```

Optional BA300 sync variables:

```env
CDSE_USERNAME=
CDSE_PASSWORD=
CDSE_CLIENT_ID=cdse-public
CDSE_CLIENT_SECRET=
BA300_SOURCE_MODE=auto
```

Only the backend reads CDSE credentials. Do not expose them through `VITE_*` frontend variables.
