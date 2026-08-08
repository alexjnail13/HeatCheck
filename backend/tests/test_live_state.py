"""
Tests for building live game state out of the database.

Covers the halftime case explicitly: a client connecting mid-game must get the
current state from stored snapshots, not an empty payload.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Game, GameStateSnapshot, Team
from app.schemas.live import LiveGameState
from app.services import live_state
from app.services.live_state import (
    build_live_update,
    compute_time_remaining,
    latest_snapshots,
    team_win_pcts,
)

GAME_DATE = date(2026, 5, 7)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        Team(id=1, nba_team_id=1610612760, abbreviation="OKC", full_name="Thunder",
             city="OKC", state="OK", conference="West", division="Northwest"),
        Team(id=2, nba_team_id=1610612747, abbreviation="LAL", full_name="Lakers",
             city="LA", state="CA", conference="West", division="Pacific"),
    ])
    session.commit()
    yield session
    session.close()


def add_game(db, gid="0042500222", status="Live", home=1, away=2, hs=None, as_=None,
             game_date=GAME_DATE, season="2025-26", season_type="Playoffs"):
    game = Game(
        nba_game_id=gid, season=season, game_date=game_date, home_team_id=home,
        away_team_id=away, home_team_score=hs, away_team_score=as_,
        status=status, season_type=season_type,
    )
    db.add(game)
    db.commit()
    return game


def add_snapshot(db, game, period, clock, home, away, minutes_ago=0):
    snap = GameStateSnapshot(
        game_id=game.id, period=period, clock=clock,
        score_home=home, score_away=away,
        captured_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(snap)
    db.commit()
    return snap


@pytest.fixture(autouse=True)
def stub_model(monkeypatch):
    """
    Replace the real model with a deterministic stand-in.

    These tests are about assembling state from the database, not about model
    accuracy — and the .pkl files may not be present in every environment.
    """
    def fake(point_differential, time_remaining_seconds, team_strength_diff):
        return round(min(max(0.5 + point_differential / 100, 0.0), 1.0), 4)

    monkeypatch.setattr(live_state, "predict_win_probability", fake)


# --- clock maths -----------------------------------------------------------


@pytest.mark.parametrize("period,clock,expected", [
    (1, "PT12M00.00S", 3 * 720 + 720),   # start of Q1 = full game
    (2, "PT06M00.00S", 2 * 720 + 360),
    (4, "PT00M00.00S", 0),               # buzzer
    (5, "PT05M00.00S", 300),             # OT counts only the current period
    (0, "", 2880),                       # not tipped off
])
def test_compute_time_remaining(period, clock, expected):
    assert compute_time_remaining(period, clock) == expected


# --- snapshots -------------------------------------------------------------


def test_latest_snapshot_wins(db):
    """Multiple snapshots accumulate; the newest is the current state."""
    game = add_game(db)
    add_snapshot(db, game, 1, "PT06M00.00S", 20, 18, minutes_ago=60)
    add_snapshot(db, game, 2, "PT02M00.00S", 48, 44, minutes_ago=30)
    newest = add_snapshot(db, game, 3, "PT04M30.00S", 78, 74, minutes_ago=1)

    result = latest_snapshots(db, [game.id])
    assert result[game.id].id == newest.id
    assert result[game.id].score_home == 78


def test_latest_snapshots_empty_input(db):
    assert latest_snapshots(db, []) == {}


# --- the halftime case -----------------------------------------------------


def test_client_connecting_at_halftime_gets_current_state(db):
    """
    The question that decided the snapshot design: a user opens a live game at
    halftime. The WebSocket only pushes future messages, so the CURRENT state
    has to come from stored snapshots.
    """
    game = add_game(db, status="Live")
    add_snapshot(db, game, 1, "PT00M00.00S", 28, 25, minutes_ago=45)
    add_snapshot(db, game, 2, "PT00M00.00S", 55, 51, minutes_ago=20)

    update = build_live_update(db, on_date=GAME_DATE)

    assert len(update.games) == 1
    state = update.games[0]
    assert state.home_team_score == 55
    assert state.away_team_score == 51
    assert state.period == 2
    assert 0.0 <= state.home_win_probability <= 1.0


def test_live_game_with_no_snapshot_falls_back_to_games_row(db):
    game = add_game(db, status="Live", hs=40, as_=38)
    update = build_live_update(db, on_date=GAME_DATE)
    state = update.games[0]
    assert (state.home_team_score, state.away_team_score) == (40, 38)


# --- win probability is computed, never stored -----------------------------


def test_final_game_has_certain_probability(db):
    game = add_game(db, status="Final", hs=110, as_=104)
    update = build_live_update(db, on_date=GAME_DATE)
    assert update.games[0].home_win_probability == 1.0

    db.query(Game).delete()
    db.commit()
    add_game(db, gid="0042500223", status="Final", hs=99, as_=112)
    update = build_live_update(db, on_date=GAME_DATE)
    assert update.games[0].home_win_probability == 0.0


def test_probability_tracks_the_score(db):
    """Same game, different stored score => different probability."""
    game = add_game(db, status="Live")
    add_snapshot(db, game, 3, "PT04M30.00S", 90, 74, minutes_ago=2)
    leading = build_live_update(db, on_date=GAME_DATE).games[0].home_win_probability

    db.query(GameStateSnapshot).delete()
    db.commit()
    add_snapshot(db, game, 3, "PT04M31.00S", 60, 84)
    trailing = build_live_update(db, on_date=GAME_DATE).games[0].home_win_probability

    assert leading > trailing


def test_model_failure_degrades_instead_of_breaking_the_feed(db, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("model not loaded")

    monkeypatch.setattr(live_state, "predict_win_probability", boom)
    game = add_game(db, status="Live")
    add_snapshot(db, game, 3, "PT04M30.00S", 78, 74)

    update = build_live_update(db, on_date=GAME_DATE)
    assert update.games[0].home_win_probability == 0.5  # degraded, not crashed


# --- team strength from our own data ---------------------------------------


def test_win_pcts_computed_from_stored_games(db):
    for i in range(3):  # home team wins 3
        add_game(db, gid=f"002250000{i}", status="Final", hs=110, as_=100,
                 game_date=date(2026, 1, 1 + i), season_type="Regular Season")
    add_game(db, gid="0022500009", status="Final", hs=95, as_=105,
             game_date=date(2026, 1, 9), season_type="Regular Season")

    pcts = team_win_pcts(db, season="2025-26")
    assert pcts[1] == 0.75  # 3-1
    assert pcts[2] == 0.25  # 1-3


def test_unknown_team_treated_as_average(db):
    """No games played => 0.5, not 0.0. An unknown team is average."""
    pcts = team_win_pcts(db, season="2025-26")
    assert pcts.get(1, 0.5) == 0.5


# --- ordering and empty states ---------------------------------------------


def test_live_games_sort_before_scheduled_and_final(db):
    add_game(db, gid="0042500001", status="Final", hs=1, as_=0)
    add_game(db, gid="0042500002", status="Scheduled")
    add_game(db, gid="0042500003", status="Live", hs=50, as_=48)

    update = build_live_update(db, on_date=GAME_DATE)
    assert [g.game_status for g in update.games] == [2, 1, 3]


def test_no_games_returns_empty_update_not_an_error(db):
    update = build_live_update(db, on_date=date(2026, 7, 30))
    assert update.games == []
    assert update.timestamp  # still timestamped


def test_update_serialises_for_the_websocket(db):
    """The payload must round-trip through the schema the frontend parses."""
    game = add_game(db, status="Live")
    add_snapshot(db, game, 3, "PT04M30.00S", 78, 74)

    payload = build_live_update(db, on_date=GAME_DATE).model_dump_json()
    assert '"games"' in payload and '"home_win_probability"' in payload

    reparsed = LiveGameState.model_validate_json(
        build_live_update(db, on_date=GAME_DATE).games[0].model_dump_json()
    )
    assert reparsed.home_team_tricode == "OKC"
