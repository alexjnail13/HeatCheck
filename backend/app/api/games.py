from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, aliased
from sqlalchemy import or_
from typing import List, Optional
from datetime import date
from app.database.session import get_db
from app.database.models import Game, Team
from app.schemas.boxscore import BoxScoreResponse
from app.schemas.game import GameResponse
from app.schemas.win_probability import WinProbabilityResponse
from app.services.boxscore_query import fetch_boxscore
from app.services.win_probability import build_curve

router = APIRouter()


def _get_game_with_abbreviations(game_id: str, db: Session):
    """Look up a game by its NBA id, returning (game, home_abbr, away_abbr)."""
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    result = (
        db.query(Game, HomeTeam.abbreviation, AwayTeam.abbreviation)
        .join(HomeTeam, Game.home_team_id == HomeTeam.id)
        .join(AwayTeam, Game.away_team_id == AwayTeam.id)
        .filter(Game.nba_game_id == game_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Game not found")
    return result


@router.get("/games", response_model=List[GameResponse])
def get_games(
    game_date: Optional[date] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    team_id: Optional[int] = Query(None, description="Filter by team ID"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    db: Session = Depends(get_db),
):
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    query = db.query(
        Game, HomeTeam.abbreviation, AwayTeam.abbreviation
    ).join(
        HomeTeam, Game.home_team_id == HomeTeam.id
    ).join(
        AwayTeam, Game.away_team_id == AwayTeam.id
    )

    if game_date:
        query = query.filter(Game.game_date == game_date)

    if team_id:
        query = query.filter(
            or_(Game.home_team_id == team_id, Game.away_team_id == team_id)
        )

    query = query.order_by(Game.game_date.desc()).offset(offset).limit(limit)
    results = query.all()

    games = []
    for game, home_abbr, away_abbr in results:
        game_dict = {
            "id": game.id,
            "nba_game_id": game.nba_game_id,
            "season": game.season,
            "game_date": game.game_date,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_team_abbreviation": home_abbr,
            "away_team_abbreviation": away_abbr,
            "home_team_score": game.home_team_score,
            "away_team_score": game.away_team_score,
            "status": game.status,
            "season_type": game.season_type,
        }
        games.append(game_dict)

    return games


@router.get("/games/{game_id}", response_model=GameResponse)
def get_game(game_id: str, db: Session = Depends(get_db)):
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    result = db.query(
        Game, HomeTeam.abbreviation, AwayTeam.abbreviation
    ).join(
        HomeTeam, Game.home_team_id == HomeTeam.id
    ).join(
        AwayTeam, Game.away_team_id == AwayTeam.id
    ).filter(
        Game.nba_game_id == game_id
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Game not found")

    game, home_abbr, away_abbr = result
    return {
        "id": game.id,
        "nba_game_id": game.nba_game_id,
        "season": game.season,
        "game_date": game.game_date,
        "home_team_id": game.home_team_id,
        "away_team_id": game.away_team_id,
        "home_team_abbreviation": home_abbr,
        "away_team_abbreviation": away_abbr,
        "home_team_score": game.home_team_score,
        "away_team_score": game.away_team_score,
        "status": game.status,
        "season_type": game.season_type,
    }


@router.get("/games/{game_id}/win-probability", response_model=WinProbabilityResponse)
def get_win_probability(game_id: str, db: Session = Depends(get_db)):
    """
    Win-probability curve for a game.

    Reads from OUR database, never live from nba_api (stats.nba.com blocks
    Render's datacenter IP). The curve-building and source selection live in
    services/win_probability.py so a live game and a finished one go through
    identical feature code.
    """
    game, home_abbr, away_abbr = _get_game_with_abbreviations(game_id, db)
    points, source = build_curve(db, game)

    return WinProbabilityResponse(
        nba_game_id=game.nba_game_id,
        home_team_abbreviation=home_abbr,
        away_team_abbreviation=away_abbr,
        points=points,
        source=source,
    )


@router.get("/games/{game_id}/boxscore", response_model=BoxScoreResponse)
def get_boxscore(game_id: str, db: Session = Depends(get_db)):
    """
    Full box score — team totals plus every player line.

    Populated by two ingestion paths that share one write path: the laptop-run
    seeder for historical games, and the Render cron job for live ones. Reads
    from Postgres either way.

    A scheduled game returns home/away as null rather than 404 — the game
    exists, its box score simply hasn't happened yet.
    """
    game, _, _ = _get_game_with_abbreviations(game_id, db)
    return fetch_boxscore(db, game)
