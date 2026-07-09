"""
Pydantic schemas for live game data sent over WebSockets.
"""

from pydantic import BaseModel


class LiveGameState(BaseModel):
    """Represents the current state of a live NBA game."""

    game_id: str
    game_status: int                # 1 = not started, 2 = in progress, 3 = final
    game_status_text: str           # e.g. "Q3 4:30", "Final", "7:00 pm ET"
    period: int
    clock: str                      # period clock e.g. "4:30"
    time_remaining_seconds: float   # total seconds left in game

    home_team_id: int
    home_team_tricode: str
    home_team_score: int
    away_team_id: int
    away_team_tricode: str
    away_team_score: int

    home_win_probability: float     # 0.0 to 1.0

    model_config = {"from_attributes": True}


class LiveUpdate(BaseModel):
    """Wrapper for a batch of live game updates sent over WebSocket."""

    games: list[LiveGameState]
    timestamp: str                  # ISO 8601 timestamp of when this update was generated