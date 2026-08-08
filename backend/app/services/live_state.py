"""
Build live game state from OUR OWN database.

This is what the WebSocket broadcasts and what the live endpoints read. It never
touches a third-party API: the cron job (app/pipeline/ingest_live.py) writes
game_state_snapshots, and everything here reads them back.

Win probability is computed HERE, at read time, from raw stored state — never
read from a stored prediction. Retraining the model changes every curve in the
app on the next request, with no re-ingestion (principle #3).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import Game, GameStateSnapshot, Team
from app.ml.inference import predict_win_probability
from app.providers.durations import parse_duration_to_seconds
from app.schemas.live import LiveGameState, LiveUpdate

logger = logging.getLogger(__name__)

REGULATION_PERIODS = 4
PERIOD_SECONDS = 12 * 60
OVERTIME_SECONDS = 5 * 60

# Mirror of the numeric codes the frontend already understands, derived from
# the status strings the ingestion job writes.
STATUS_CODE = {"Scheduled": 1, "Live": 2, "Final": 3}


def compute_time_remaining(period: int, clock: str | None) -> float:
    """
    Total seconds left in the game.

    Regulation: whole periods still to play, plus what's on the clock now.
    Overtime: only the current OT period, since there's no guaranteed next one.
    """
    on_clock = parse_duration_to_seconds(clock) or 0

    if period <= 0:
        return REGULATION_PERIODS * PERIOD_SECONDS  # not tipped off yet
    if period <= REGULATION_PERIODS:
        return (REGULATION_PERIODS - period) * PERIOD_SECONDS + on_clock
    return float(on_clock)


def team_win_pcts(db: Session, season: str | None = None) -> dict[int, float]:
    """
    Regular-season win percentage per team.id, from stored games.

    The old live fetcher took wins/losses off the scoreboard payload. Computing
    them from our own games table means team strength is available whether or
    not the feed is up, and stays consistent with the standings page.
    """
    if season is None:
        season = db.query(func.max(Game.season)).scalar()

    record: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    completed = (
        db.query(Game)
        .filter(
            Game.season == season,
            Game.status == "Final",
            Game.season_type == "Regular Season",
            Game.home_team_score.isnot(None),
            Game.away_team_score.isnot(None),
        )
        .all()
    )
    for game in completed:
        if game.home_team_score > game.away_team_score:
            winner, loser = game.home_team_id, game.away_team_id
        else:
            winner, loser = game.away_team_id, game.home_team_id
        record[winner][0] += 1
        record[loser][1] += 1

    pcts: dict[int, float] = {}
    for team_id, (wins, losses) in record.items():
        played = wins + losses
        # 0.5 for a team with no games yet — an unknown team is an average one,
        # not a hopeless one.
        pcts[team_id] = wins / played if played else 0.5
    return pcts


def latest_snapshots(db: Session, game_ids: list[int]) -> dict[int, GameStateSnapshot]:
    """
    Most recent snapshot per game, keyed by game_id.

    Ordered by captured_at — the snapshot table has no event_num, because a
    polled scoreboard gives moments, not numbered events.
    """
    if not game_ids:
        return {}

    newest = (
        db.query(
            GameStateSnapshot.game_id,
            func.max(GameStateSnapshot.captured_at).label("captured_at"),
        )
        .filter(GameStateSnapshot.game_id.in_(game_ids))
        .group_by(GameStateSnapshot.game_id)
        .subquery()
    )

    rows = (
        db.query(GameStateSnapshot)
        .join(
            newest,
            (GameStateSnapshot.game_id == newest.c.game_id)
            & (GameStateSnapshot.captured_at == newest.c.captured_at),
        )
        .all()
    )
    return {row.game_id: row for row in rows}


def build_game_state(
    game: Game,
    home: Team,
    away: Team,
    snapshot: GameStateSnapshot | None,
    win_pcts: dict[int, float],
) -> LiveGameState:
    """
    Assemble one game's live state, running the model fresh.

    Scores prefer the snapshot (updated every poll) over the games row (updated
    less often), so an in-progress game shows the latest known score.
    """
    status_code = STATUS_CODE.get(game.status, 1)

    if snapshot is not None:
        period = snapshot.period
        clock = snapshot.clock or ""
        home_score = snapshot.score_home
        away_score = snapshot.score_away
    else:
        period = REGULATION_PERIODS if status_code == 3 else 0
        clock = ""
        home_score = game.home_team_score or 0
        away_score = game.away_team_score or 0

    time_remaining = compute_time_remaining(period, clock)
    strength_diff = win_pcts.get(game.home_team_id, 0.5) - win_pcts.get(
        game.away_team_id, 0.5
    )

    if status_code == 3:
        # Final: the result is known, so don't ask the model about it.
        home_win_prob = 1.0 if home_score > away_score else 0.0
    elif status_code == 2:
        try:
            home_win_prob = predict_win_probability(
                point_differential=home_score - away_score,
                time_remaining_seconds=time_remaining,
                team_strength_diff=strength_diff,
            )
        except Exception as exc:
            # A model failure must not take the whole feed down.
            logger.error("WP prediction failed for %s: %s", game.nba_game_id, exc)
            home_win_prob = 0.5
    else:
        # Pre-tip: team strength only, nudged around an even baseline.
        home_win_prob = round(min(max(0.5 + strength_diff / 2, 0.0), 1.0), 4)

    return LiveGameState(
        game_id=game.nba_game_id,
        game_status=status_code,
        game_status_text=game.status,
        period=period,
        clock=clock,
        time_remaining_seconds=time_remaining,
        home_team_id=home.nba_team_id,
        home_team_tricode=home.abbreviation,
        home_team_score=home_score,
        away_team_id=away.nba_team_id,
        away_team_tricode=away.abbreviation,
        away_team_score=away_score,
        home_win_probability=home_win_prob,
    )


def build_live_update(db: Session, on_date: date | None = None) -> LiveUpdate:
    """
    Every game for a given date, with a freshly computed win probability.

    Defaults to the most recent date that has games, rather than today: out of
    season "today" is empty, and an empty feed is indistinguishable from a
    broken one to anyone looking at the UI.
    """
    if on_date is None:
        on_date = db.query(func.max(Game.game_date)).filter(
            Game.status.in_(["Live", "Final"])
        ).scalar()
        live_dates = db.query(func.max(Game.game_date)).filter(
            Game.status == "Live"
        ).scalar()
        if live_dates:
            on_date = live_dates

    games = db.query(Game).filter(Game.game_date == on_date).all() if on_date else []

    if not games:
        return LiveUpdate(
            games=[], timestamp=datetime.now(timezone.utc).isoformat()
        )

    teams = {t.id: t for t in db.query(Team).all()}
    snapshots = latest_snapshots(db, [g.id for g in games])
    win_pcts = team_win_pcts(db)

    states: list[LiveGameState] = []
    for game in games:
        home, away = teams.get(game.home_team_id), teams.get(game.away_team_id)
        if home is None or away is None:
            logger.warning("Game %s references an unknown team", game.nba_game_id)
            continue
        states.append(
            build_game_state(game, home, away, snapshots.get(game.id), win_pcts)
        )

    # Live games first, then scheduled, then final — what a user cares about.
    states.sort(key=lambda s: {2: 0, 1: 1, 3: 2}.get(s.game_status, 3))

    return LiveUpdate(
        games=states, timestamp=datetime.now(timezone.utc).isoformat()
    )
