"""Pydantic schema for the standings endpoint."""
from pydantic import BaseModel


class StandingsRow(BaseModel):
    """One team's standing within its conference."""
    team_name: str
    conference: str          # "East" / "West"
    seed: int                # rank within conference
    wins: int
    losses: int
    win_pct: float           # the sort key
    games_behind: float
