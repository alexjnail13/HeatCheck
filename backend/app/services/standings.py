"""
Standings business logic — the single source of truth for computing NBA standings.

Both the /standings API route and the 'Ask Heat Check' chatbot import this, so
the logic lives in exactly one place (no duplicate logic to drift apart).

Standings are computed from OUR OWN data (the games + teams tables) rather than
fetched live from nba_api. Every field a standings row needs is derivable from
games we already store, so there's no reason to depend on an external service
that may be unreachable (stats.nba.com blocks datacenter IPs, which broke this
endpoint in production).
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import Game, Team
from app.schemas.standings import StandingsRow


def fetch_standings(db: Session, season: Optional[str] = None) -> List[StandingsRow]:
    """
    Compute conference standings for a season from completed games.

    Args:
        db: SQLAlchemy session.
        season: Season string as stored on Game.season (e.g. "2024-25").
            If None, defaults to the most recent season present in the database,
            so the endpoint stays correct no matter which season was seeded.

    Returns:
        StandingsRow list, ordered by conference then seed (1 = best record).
    """
    if season is None:
        # "2025-26" > "2024-25" lexicographically, so max() picks the latest.
        season = db.query(func.max(Game.season)).scalar()

    teams: List[Team] = db.query(Team).all()

    # team.id -> [wins, losses]
    record: Dict[int, List[int]] = {t.id: [0, 0] for t in teams}

    completed = (
        db.query(Game)
        .filter(Game.season == season, Game.status == "Final")
        .all()
    )

    for game in completed:
        if game.home_team_score is None or game.away_team_score is None:
            continue  # not actually final — skip rather than miscount

        if game.home_team_score > game.away_team_score:
            winner, loser = game.home_team_id, game.away_team_id
        else:
            winner, loser = game.away_team_id, game.home_team_id

        if winner in record:
            record[winner][0] += 1
        if loser in record:
            record[loser][1] += 1

    # Group teams by conference so we can rank within each.
    # entry = (team, wins, losses, win_pct)
    by_conference: Dict[str, List[Tuple[Team, int, int, float]]] = defaultdict(list)
    for team in teams:
        wins, losses = record[team.id]
        played = wins + losses
        win_pct = wins / played if played else 0.0
        by_conference[team.conference].append((team, wins, losses, win_pct))

    rows: List[StandingsRow] = []
    for conference, entries in by_conference.items():
        # Best record first; wins breaks ties between equal percentages.
        entries.sort(key=lambda e: (e[3], e[1]), reverse=True)

        leader_wins, leader_losses = entries[0][1], entries[0][2]

        for seed, (team, wins, losses, win_pct) in enumerate(entries, start=1):
            # Standard GB formula, relative to the conference leader.
            games_behind = ((leader_wins - wins) + (losses - leader_losses)) / 2

            rows.append(
                StandingsRow(
                    team_name=team.full_name,
                    conference=conference,
                    seed=seed,
                    wins=wins,
                    losses=losses,
                    win_pct=round(win_pct, 3),
                    games_behind=float(games_behind),
                )
            )

    return rows
