"""
Shared feature-engineering helpers for the win-probability model.

This module is the single source of truth for turning raw play-by-play
events into model features. Both the offline training pipeline
(`pipeline/fetch_pbp.py`) and the live inference endpoint import from here,
so training and serving compute features identically (no train/serve skew).
"""

import re

from sqlalchemy.orm import Session

from app.database.models import Game


def parse_clock(clock_str: str) -> float:
    """
    Parse PlayByPlayV3's ISO-8601 game clock into seconds remaining
    in the current period.

    Example: "PT04M30.00S" -> 270.0
    """
    if not clock_str:
        return 0.0
    match = re.match(r"PT(\d+)M([\d.]+)S", clock_str)
    if match:
        minutes = int(match.group(1))
        seconds = float(match.group(2))
        return minutes * 60 + seconds
    return 0.0


def calc_time_remaining(period: int, clock_str: str) -> float:
    """
    Convert quarter number + period clock into total seconds remaining
    in the game (regulation only — caps at period 4).

        (4 - period) * 12 * 60  +  seconds_left_in_period

    Overtime (period > 4) is treated as only the current OT clock remaining.
    """
    period_seconds = parse_clock(clock_str)
    if period > 4:
        return period_seconds
    remaining_full_quarters = (4 - period) * 12 * 60
    return remaining_full_quarters + period_seconds


def get_team_win_pcts(db: Session) -> dict[int, float]:
    """
    Compute each team's win percentage from completed games.

    Returns {internal_team_id: win_pct}.
    """
    games = db.query(Game).filter(Game.status == "Final").all()

    wins: dict[int, int] = {}
    total: dict[int, int] = {}

    for g in games:
        for tid in [g.home_team_id, g.away_team_id]:
            total[tid] = total.get(tid, 0) + 1

        if g.home_team_score > g.away_team_score:
            wins[g.home_team_id] = wins.get(g.home_team_id, 0) + 1
        else:
            wins[g.away_team_id] = wins.get(g.away_team_id, 0) + 1

    return {tid: wins.get(tid, 0) / total[tid] for tid in total}


def extract_event_features(event) -> dict | None:
    """
    Turn one raw play-by-play event into the features shared by training
    and inference. Returns None for events that should be skipped
    (missing/un-parseable score or period), so callers can `continue`.

    Returned dict:
        {
          "period": int,
          "time_remaining_seconds": float,
          "point_differential": int,   # home - away
          "score_home": int,
          "score_away": int,
        }
    """
    score_home = event.get("scoreHome")
    score_away = event.get("scoreAway")
    period = event.get("period")
    clock = event.get("clock", "")

    if score_home is None or score_away is None or period is None:
        return None

    try:
        score_home = int(score_home)
        score_away = int(score_away)
    except (ValueError, TypeError):
        return None

    return {
        "period": period,
        "time_remaining_seconds": calc_time_remaining(period, clock or ""),
        "point_differential": score_home - score_away,
        "score_home": score_home,
        "score_away": score_away,
    }
