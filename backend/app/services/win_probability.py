"""
Win-probability curve for one game, from whichever source has the game.

Two tables can describe how a game unfolded:

    play_by_play          ~450 rows, seeded after the game from stats.nba.com
    game_state_snapshots  ~90 rows, written every poll while the game is live

They are deliberately separate (interleaving them would draw one curve from two
sources at two resolutions). This module owns the handoff: play-by-play when we
have it, snapshots otherwise. A live game reads snapshots; once the seeder
backfills the real events, the same game silently upgrades to the finer curve.

Both paths run through ml.features.extract_event_features, so the features
behind a live point and a historical point are computed by identical code —
the same no-train/serve-skew rule that module already enforces.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.database.models import Game, GameStateSnapshot, PlayByPlay
from app.ml.features import extract_event_features, get_team_win_pcts
from app.ml.inference import predict_win_probability
from app.schemas.win_probability import WinProbabilityPoint

logger = logging.getLogger(__name__)

SOURCE_PLAY_BY_PLAY = "play_by_play"
SOURCE_SNAPSHOTS = "snapshots"
SOURCE_NONE = "none"


def _events_from_play_by_play(db: Session, game: Game) -> list[dict]:
    """
    Ordered by event_num — the sequence key the endpoint has always used.
    SQL rows have no inherent order, so this is what rebuilds the game.
    """
    rows = (
        db.query(PlayByPlay)
        .filter(PlayByPlay.game_id == game.id)
        .order_by(PlayByPlay.event_num)
        .all()
    )
    return [
        {
            "scoreHome": r.score_home,
            "scoreAway": r.score_away,
            "period": r.period,
            "clock": r.clock,
        }
        for r in rows
    ]


def _events_from_snapshots(db: Session, game: Game) -> list[dict]:
    """
    Ordered by captured_at — snapshots have no event numbering, because a
    polled scoreboard reports moments rather than numbered events.
    """
    rows = (
        db.query(GameStateSnapshot)
        .filter(GameStateSnapshot.game_id == game.id)
        .order_by(GameStateSnapshot.captured_at)
        .all()
    )
    return [
        {
            "scoreHome": r.score_home,
            "scoreAway": r.score_away,
            "period": r.period,
            "clock": r.clock,
        }
        for r in rows
    ]


def select_events(db: Session, game: Game) -> tuple[list[dict], str]:
    """
    Pick the source for this game's curve.

    Play-by-play wins whenever it exists: ~450 events versus ~90 polls is a far
    better curve, and it's the authoritative record. Snapshots cover the window
    where a game is live and no play-by-play has been seeded yet.
    """
    events = _events_from_play_by_play(db, game)
    if events:
        return events, SOURCE_PLAY_BY_PLAY

    events = _events_from_snapshots(db, game)
    if events:
        return events, SOURCE_SNAPSHOTS

    return [], SOURCE_NONE


def build_curve(db: Session, game: Game) -> tuple[list[WinProbabilityPoint], str]:
    """
    Build the full curve. Returns (points, source).

    Probabilities are computed here on every request, never read from storage,
    so retraining the model reshapes every historical curve in the app without
    touching a row (principle #3).
    """
    events, source = select_events(db, game)
    if not events:
        return [], source

    # Constant for the whole game, so computed once rather than per event.
    win_pcts = get_team_win_pcts(db)
    strength_diff = win_pcts.get(game.home_team_id, 0.5) - win_pcts.get(
        game.away_team_id, 0.5
    )

    points: list[WinProbabilityPoint] = []
    for event in events:
        feats = extract_event_features(event)
        if feats is None:
            continue  # unusable row — skip it rather than fail the request

        try:
            prob = predict_win_probability(
                point_differential=feats["point_differential"],
                time_remaining_seconds=feats["time_remaining_seconds"],
                team_strength_diff=strength_diff,
            )
        except Exception as exc:
            logger.error("WP prediction failed for %s: %s", game.nba_game_id, exc)
            continue

        points.append(
            WinProbabilityPoint(
                period=feats["period"],
                time_remaining_seconds=feats["time_remaining_seconds"],
                home_win_probability=prob,
                home_score=feats["score_home"],
                away_score=feats["score_away"],
            )
        )

    return points, source
