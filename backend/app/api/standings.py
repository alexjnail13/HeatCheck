from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database.session import get_db
from app.schemas.standings import StandingsRow
from app.services.standings import fetch_standings

router = APIRouter()


@router.get("/standings", response_model=List[StandingsRow])
def get_standings(
    season: str = Query("2024-25", description="Season, e.g. 2024-25"),
    db: Session = Depends(get_db),
):
    # Thin HTTP adapter: business logic lives in services/standings.py.
    # Standings are computed from our own games table — no external call.
    try:
        return fetch_standings(db, season)
    except Exception:
        raise HTTPException(status_code=503, detail="Standings source unavailable")
