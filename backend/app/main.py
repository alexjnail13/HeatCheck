"""
FastAPI entry point for Heat Check application.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database.session import engine, Base
from app.api import teams, games, live, standings, chat, auth
from app.ml.inference import load_model
from app.live.fetcher import start_polling_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for the application."""
    # --- startup ---
    Base.metadata.create_all(bind=engine)
    load_model()
    print("✅ ML model and scaler loaded successfully.")
    asyncio.create_task(start_polling_loop())
    print("🏀 Live game polling loop started.")
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