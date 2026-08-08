"""
Read side of box scores.

Writes live in boxscore_store.py; this is the query path the API uses. Kept
separate because they have opposite shapes: writes take provider-neutral
dataclasses and upsert, reads take a game and return presentation-ready rows.

Everything derivable is derived here rather than stored — percentages from
makes/attempts, total rebounds from the offensive/defensive split, display
minutes from seconds. One place computes them, so they can never disagree with
the counts they came from.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.models import Game, Player, PlayerGameStats, Team, TeamGameStats
from app.schemas.boxscore import (
    BoxScoreResponse,
    PlayerBoxScoreRow,
    TeamBoxScoreRow,
)


def pct(made: int, attempted: int) -> float | None:
    """
    Shooting percentage, or None when nobody shot.

    None rather than 0.0: a player who took no threes did not shoot 0%, and
    averaging a fake zero into anything downstream would be wrong.
    """
    if not attempted:
        return None
    return round(made / attempted, 3)


def format_minutes(seconds: int | None) -> str:
    """1961 -> '32:41'. '--' for a DNP, which is not the same as 0:00."""
    if seconds is None:
        return "--"
    return f"{seconds // 60}:{seconds % 60:02d}"


def player_row(stat: PlayerGameStats, player: Player) -> PlayerBoxScoreRow:
    return PlayerBoxScoreRow(
        player_id=player.id,
        full_name=player.full_name,
        position=player.position,
        jersey_number=player.jersey_number,
        started=stat.started,
        played=stat.seconds_played is not None,
        seconds_played=stat.seconds_played,
        minutes=format_minutes(stat.seconds_played),
        points=stat.points,
        fgm=stat.fgm,
        fga=stat.fga,
        fg_pct=pct(stat.fgm, stat.fga),
        fg3m=stat.fg3m,
        fg3a=stat.fg3a,
        fg3_pct=pct(stat.fg3m, stat.fg3a),
        ftm=stat.ftm,
        fta=stat.fta,
        ft_pct=pct(stat.ftm, stat.fta),
        oreb=stat.oreb,
        dreb=stat.dreb,
        rebounds=stat.oreb + stat.dreb,  # derived, never stored
        assists=stat.assists,
        steals=stat.steals,
        blocks=stat.blocks,
        turnovers=stat.turnovers,
        fouls=stat.fouls,
        plus_minus=stat.plus_minus,
    )


def team_row(
    stat: TeamGameStats, team: Team, players: list[PlayerBoxScoreRow]
) -> TeamBoxScoreRow:
    return TeamBoxScoreRow(
        team_id=team.id,
        abbreviation=team.abbreviation,
        full_name=team.full_name,
        is_home=stat.is_home,
        points=stat.points,
        fgm=stat.fgm,
        fga=stat.fga,
        fg_pct=pct(stat.fgm, stat.fga),
        fg3m=stat.fg3m,
        fg3a=stat.fg3a,
        fg3_pct=pct(stat.fg3m, stat.fg3a),
        ftm=stat.ftm,
        fta=stat.fta,
        ft_pct=pct(stat.ftm, stat.fta),
        oreb=stat.oreb,
        dreb=stat.dreb,
        rebounds=stat.oreb + stat.dreb,
        assists=stat.assists,
        steals=stat.steals,
        blocks=stat.blocks,
        turnovers=stat.turnovers,
        fouls=stat.fouls,
        team_rebounds=stat.team_rebounds,
        team_turnovers=stat.team_turnovers,
    )


def sort_players(rows: list[PlayerBoxScoreRow]) -> list[PlayerBoxScoreRow]:
    """
    Starters first, then by minutes played, then by points.

    Ordered from the data rather than from the order rows came back in — SQL
    rows have no inherent order, and the provider's ordering is not a contract.
    """
    return sorted(
        rows,
        key=lambda r: (not r.started, -(r.seconds_played or 0), -r.points),
    )


def fetch_boxscore(db: Session, game: Game) -> BoxScoreResponse:
    """
    Assemble a game's full box score.

    Returns a response with home/away set to None when nothing has been
    ingested yet — a scheduled game legitimately has no box score, and that is
    not an error the caller should have to catch.
    """
    team_stats = db.query(TeamGameStats).filter(TeamGameStats.game_id == game.id).all()
    teams = {t.id: t for t in db.query(Team).all()}

    player_stats = (
        db.query(PlayerGameStats, Player)
        .join(Player, Player.id == PlayerGameStats.player_id)
        .filter(PlayerGameStats.game_id == game.id)
        .all()
    )

    players_by_team: dict[int, list[PlayerBoxScoreRow]] = {}
    for stat, player in player_stats:
        players_by_team.setdefault(stat.team_id, []).append(player_row(stat, player))

    home = away = None
    for stat in team_stats:
        team = teams.get(stat.team_id)
        if team is None:
            continue
        row = team_row(stat, team, [])
        row.players = sort_players(players_by_team.get(stat.team_id, []))
        if stat.is_home:
            home = row
        else:
            away = row

    return BoxScoreResponse(
        nba_game_id=game.nba_game_id,
        status=game.status,
        is_live=game.status == "Live",
        home=home,
        away=away,
    )
