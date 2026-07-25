from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, aliased
from sqlalchemy import or_
from typing import List, Optional
from datetime import date
from app.database.session import get_db
from app.database.models import Game, Team, PlayByPlay
from app.schemas.game import GameResponse
from app.schemas.win_probability import WinProbabilityResponse, WinProbabilityPoint
from app.ml.features import get_team_win_pcts, extract_event_features
from app.ml.inference import predict_win_probability

router = APIRouter()


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
    # 1. Confirm the game exists (reuse the aliased-join so we also get abbreviations)
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

    # 2. Read play-by-play from OUR database (seeded by pipeline/seed_pbp.py),
    #    not live from nba_api — stats.nba.com blocks Render's datacenter IP.
    #    ORDER BY event_num rebuilds the game chronologically (rows have no
    #    inherent order).
    events = (
        db.query(PlayByPlay)
        .filter(PlayByPlay.game_id == game.id)
        .order_by(PlayByPlay.event_num)
        .all()
    )

    # 3. team_strength_diff — constant for the game, computed once
    win_pcts = get_team_win_pcts(db)
    home_wp = win_pcts.get(game.home_team_id, 0.5)
    away_wp = win_pcts.get(game.away_team_id, 0.5)
    strength_diff = home_wp - away_wp

    # 4. Walk each event → predict → build the series. We rebuild the raw event
    #    dict and reuse extract_event_features so features are computed by the
    #    SAME code as training/inference (no train/serve skew).
    points: list[WinProbabilityPoint] = []
    for event in events:
        feats = extract_event_features({
            "scoreHome": event.score_home,
            "scoreAway": event.score_away,
            "period": event.period,
            "clock": event.clock,
        })
        if feats is None:
            continue  # skip rows with no score/period — don't fail the request

        prob = predict_win_probability(
            point_differential=feats["point_differential"],
            time_remaining_seconds=feats["time_remaining_seconds"],
            team_strength_diff=strength_diff,
        )

        points.append(WinProbabilityPoint(
            period=feats["period"],
            time_remaining_seconds=feats["time_remaining_seconds"],
            home_win_probability=prob,
            home_score=feats["score_home"],
            away_score=feats["score_away"],
        ))

    # 5. Return the full series + metadata
    return WinProbabilityResponse(
        nba_game_id=game.nba_game_id,
        home_team_abbreviation=home_abbr,
        away_team_abbreviation=away_abbr,
        points=points,
    )
