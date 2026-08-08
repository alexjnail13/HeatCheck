"""
End-to-end WebSocket test: connect, receive state built from Postgres.

Mounts only the live router rather than the whole app, so this doesn't depend
on a Gemini key or the trained model artifacts being present.
"""

from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import live as live_router
from app.database.models import Base, Game, GameStateSnapshot, Team
from app.live import fetcher
from app.services import live_state

GAME_DATE = date(2026, 5, 7)


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """A live game in a real database, with the fetcher pointed at it."""
    url = f"sqlite:///{tmp_path/'ws.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    db = Session()
    db.add_all([
        Team(id=1, nba_team_id=1610612760, abbreviation="OKC", full_name="Thunder",
             city="OKC", state="OK", conference="West", division="Northwest"),
        Team(id=2, nba_team_id=1610612747, abbreviation="LAL", full_name="Lakers",
             city="LA", state="CA", conference="West", division="Pacific"),
    ])
    game = Game(
        nba_game_id="0042500222", season="2025-26", game_date=GAME_DATE,
        home_team_id=1, away_team_id=2, status="Live", season_type="Playoffs",
    )
    db.add(game)
    db.commit()
    db.add(GameStateSnapshot(
        game_id=game.id, period=3, clock="PT04M30.00S",
        score_home=78, score_away=74,
        captured_at=datetime.now(timezone.utc),
    ))
    db.commit()
    db.close()

    monkeypatch.setattr(fetcher, "SessionLocal", Session)
    monkeypatch.setattr(
        live_state, "predict_win_probability",
        lambda **kw: round(0.5 + kw["point_differential"] / 100, 4),
    )

    app = FastAPI()
    app.include_router(live_router.router, prefix="/api/v1")
    return app


def test_client_receives_state_immediately_on_connect(wired):
    """
    No waiting for the next broadcast tick, and no empty first frame — the
    halftime case, end to end over a real socket.
    """
    with TestClient(wired) as client:
        with client.websocket_connect("/api/v1/ws/live") as ws:
            update = ws.receive_json()

    assert len(update["games"]) == 1
    game = update["games"][0]
    assert game["game_id"] == "0042500222"
    assert game["home_team_score"] == 78
    assert game["away_team_score"] == 74
    assert game["home_team_tricode"] == "OKC"
    assert game["period"] == 3
    assert 0.0 <= game["home_win_probability"] <= 1.0
    assert update["timestamp"]


def test_payload_carries_no_stored_prediction_fields(wired):
    """State is raw; probability is derived at read time, not persisted."""
    with TestClient(wired) as client:
        with client.websocket_connect("/api/v1/ws/live") as ws:
            update = ws.receive_json()

    snapshot_columns = {c.name for c in GameStateSnapshot.__table__.columns}
    assert "home_win_probability" not in snapshot_columns
    # ...yet the client still gets one.
    assert "home_win_probability" in update["games"][0]


def test_client_registry_tracks_connections(wired):
    assert fetcher.client_count() == 0
    with TestClient(wired) as client:
        with client.websocket_connect("/api/v1/ws/live") as ws:
            ws.receive_json()
            assert fetcher.client_count() == 1
    assert fetcher.client_count() == 0
