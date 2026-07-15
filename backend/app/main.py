from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api.routes import router
from app.settings import get_settings

settings = get_settings()
db.init_db(settings.db_path)

app = FastAPI(
    title="Burned Area Explorer API",
    description="Stateful workflow-driven EO workflow orchestration demo.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
