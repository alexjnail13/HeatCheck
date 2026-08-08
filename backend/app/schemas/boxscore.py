"""
Pydantic schemas for box score responses.

Percentages appear HERE but are not stored anywhere — they're computed at read
time from the makes and attempts in player_game_stats. Storing them would let
them drift out of sync with the counts they came from, and would throw away
attempt volume, which the Phase C prop models need as a feature.
"""

from pydantic import BaseModel


class PlayerBoxScoreRow(BaseModel):
    """One player's line."""

    player_id: int
    full_name: str
    position: str | None = None
    jersey_number: str | None = None
    started: bool
    played: bool

    # Stored as seconds; formatted for display so the frontend doesn't
    # reimplement the conversion.
    seconds_played: int | None = None
    minutes: str = "--"

    points: int
    fgm: int
    fga: int
    fg_pct: float | None = None
    fg3m: int
    fg3a: int
    fg3_pct: float | None = None
    ftm: int
    fta: int
    ft_pct: float | None = None
    oreb: int
    dreb: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    plus_minus: int | None = None


class TeamBoxScoreRow(BaseModel):
    """One team's totals, plus its players."""

    team_id: int
    abbreviation: str
    full_name: str
    is_home: bool

    points: int
    fgm: int
    fga: int
    fg_pct: float | None = None
    fg3m: int
    fg3a: int
    fg3_pct: float | None = None
    ftm: int
    fta: int
    ft_pct: float | None = None
    oreb: int
    dreb: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    # Null for games seeded from stats.nba.com, which doesn't break these out.
    # A visible gap is better than a fabricated number.
    team_rebounds: int | None = None
    team_turnovers: int | None = None

    players: list[PlayerBoxScoreRow] = []


class BoxScoreResponse(BaseModel):
    """Full box score for one game."""

    nba_game_id: str
    status: str
    # "complete" once the game is final, "live" while it's still updating.
    # The frontend uses this to decide whether to keep polling.
    is_live: bool
    home: TeamBoxScoreRow | None = None
    away: TeamBoxScoreRow | None = None
