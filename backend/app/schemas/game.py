from pydantic import BaseModel
from datetime import date
from typing import Optional


class GameResponse(BaseModel):
    id: int
    nba_game_id: str
    season: str
    game_date: date
    home_team_id: int
    away_team_id: int
    home_team_abbreviation: str
    away_team_abbreviation: str
    home_team_score: Optional[int] = None
    away_team_score: Optional[int] = None
    status: str
    season_type: str

    class Config:
        from_attributes = True