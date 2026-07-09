from fastapi import APIRouter, Query, HTTPException
from typing import List

from app.schemas.standings import StandingsRow
from app.services.standings import fetch_standings

router = APIRouter()


@router.get("/standings", response_model=List[StandingsRow])
def get_standings(season: str = Query("2025-26", description="Season, e.g. 2025-26")):
    # Thin HTTP adapter: business logic lives in services/standings.py.
    # Plain def -> FastAPI threadpools the blocking nba_api call.
    try:
        return fetch_standings(season)
    except Exception:
        raise HTTPException(status_code=503, detail="Standings source unavailable")
