"""
Pydantic schemas for the win-probability curve endpoint.
"""

from pydantic import BaseModel


class WinProbabilityPoint(BaseModel):
    """A single point on the win-probability curve (one scoring event)."""

    period: int
    time_remaining_seconds: float
    home_win_probability: float       # 0.0 to 1.0
    home_score: int
    away_score: int


class WinProbabilityResponse(BaseModel):
    """The full win-probability time series for one game, plus metadata."""

    nba_game_id: str
    home_team_abbreviation: str
    away_team_abbreviation: str
    points: list[WinProbabilityPoint]
    # Which table the curve came from: "play_by_play" (seeded after the game,
    # ~450 events), "snapshots" (polled while live, ~90 points), or "none".
    # Exposed so the UI can be honest about resolution instead of implying a
    # coarse live curve is as detailed as a finished one.
    source: str = "play_by_play"
