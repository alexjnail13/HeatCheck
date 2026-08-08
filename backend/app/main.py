"""
FastAPI entry point for Heat Check application.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import teams, games, live, standings, chat, auth
from app.live.fetcher import start_broadcast_loop
from app.ml.inference import load_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for the application."""
    # --- startup ---
    # NOTE: schema is now owned by Alembic, not create_all().
    #
    # create_all() only ever CREATES missing tables — it never ALTERs an
    # existing one. That silently no-ops on any change to a table that already
    # exists in production (e.g. adding games.tipoff_utc), so the app would boot
    # against a schema that doesn't match its models. Run migrations instead:
    #
    #     alembic upgrade head
    #
    # In production this belongs in the Render build/pre-deploy command, not
    # here: it must run once per deploy, not once per instance.
    load_model()
    print("✅ ML model and scaler loaded successfully.")
    #
    # INGESTION has moved out of the web service into app/pipeline/ingest_live.py,
    # which runs as a Render Cron Job. It could not stay here because it called
    # nba_api (blocked from Render's IP) on the request path, died with the
    # service on free-tier spin-down, and duplicated its WRITES once more than
    # one instance was running.
    #
    # What starts below is NOT that loop. It only reads our own Postgres and
    # pushes to connected WebSocket clients — no third party, no writes, so
    # running one copy per instance is harmless and spin-down costs nothing
    # (there are no connected clients to serve anyway).
    asyncio.create_task(start_broadcast_loop())
    print("📡 Live broadcast loop started (reads from Postgres).")
    yield
    # --- shutdown ---
    print("👋 Heat Check shutting down.")


app = FastAPI(title="Heat Check API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teams.router, prefix="/api/v1")
app.include_router(games.router, prefix="/api/v1")
app.include_router(live.router, prefix="/api/v1")
app.include_router(standings.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")