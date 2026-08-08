"""
Tests for the box score and win-probability read endpoints.

Exercises the real routes through FastAPI's TestClient against a real database,
with only the model stubbed.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import games as games_api
from app.database.models import (
    Base,
    Game,
    GameStateSnapshot,
    PlayByPlay,
    Player,
    PlayerGameStats,
    Team,
    TeamGameStats,
)
from app.database.session import get_db
from app.services import win_probability as wp_service
from app.services.boxscore_query import format_minutes, pct

GAME_DATE = date(2026, 5, 7)
GID = "0042500222"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path/'read.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    db = Session()
    db.add_all([
        Team(id=1, nba_team_id=1610612752, abbreviation="NYK", full_name="Knicks",
             city="New York", state="NY", conference="East", division="Atlantic"),
        Team(id=2, nba_team_id=1610612765, abbreviation="DET", full_name="Pistons",
             city="Detroit", state="MI", conference="East", division="Central"),
    ])
    db.add(Game(id=1, nba_game_id=GID, season="2025-26", game_date=GAME_DATE,
                home_team_id=1, away_team_id=2, home_team_score=110,
                away_team_score=104, status="Final", season_type="Playoffs"))
    db.commit()
    db.close()

    monkeypatch.setattr(
        wp_service, "predict_win_probability",
        lambda **kw: round(min(max(0.5 + kw["point_differential"] / 100, 0.0), 1.0), 4),
    )

    app = FastAPI()
    app.include_router(games_api.router, prefix="/api/v1")

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    test_client = TestClient(app)
    test_client.Session = Session  # let tests seed more data
    return test_client


def seed_boxscore(Session):
    db = Session()
    db.add_all([
        Player(id=1, full_name="Jalen Brunson", first_name="Jalen",
               last_name="Brunson", position="G", jersey_number="11"),
        Player(id=2, full_name="Bench Player", first_name="Bench",
               last_name="Player", position=None, jersey_number="9"),
        Player(id=3, full_name="Cade Cunningham", first_name="Cade",
               last_name="Cunningham", position="G", jersey_number="2"),
    ])
    db.add_all([
        TeamGameStats(game_id=1, team_id=1, is_home=True, points=110, fgm=40, fga=85,
                      fg3m=12, fg3a=33, ftm=18, fta=22, oreb=9, dreb=33, assists=24,
                      steals=7, blocks=4, turnovers=11, fouls=18, team_rebounds=5,
                      team_turnovers=1),
        TeamGameStats(game_id=1, team_id=2, is_home=False, points=104, fgm=38, fga=88,
                      fg3m=10, fg3a=30, ftm=18, fta=24, oreb=11, dreb=30, assists=21,
                      steals=5, blocks=3, turnovers=13, fouls=20),
    ])
    db.add_all([
        PlayerGameStats(game_id=1, player_id=1, team_id=1, started=True,
                        seconds_played=2467, points=45, fgm=16, fga=28, fg3m=5,
                        fg3a=11, ftm=8, fta=9, oreb=1, dreb=5, assists=7, steals=2,
                        blocks=0, turnovers=3, fouls=2, plus_minus=12),
        PlayerGameStats(game_id=1, player_id=2, team_id=1, started=False,
                        seconds_played=None, points=0, fgm=0, fga=0, fg3m=0, fg3a=0,
                        ftm=0, fta=0, oreb=0, dreb=0, assists=0, steals=0, blocks=0,
                        turnovers=0, fouls=0, plus_minus=None),
        PlayerGameStats(game_id=1, player_id=3, team_id=2, started=True,
                        seconds_played=2300, points=30, fgm=11, fga=24, fg3m=3,
                        fg3a=9, ftm=5, fta=6, oreb=2, dreb=7, assists=9, steals=1,
                        blocks=1, turnovers=4, fouls=3, plus_minus=-8),
    ])
    db.commit()
    db.close()


# --- derived-value helpers -------------------------------------------------


def test_pct_returns_none_when_nothing_attempted():
    """A player who took no threes did not shoot 0% — that's a real distinction."""
    assert pct(0, 0) is None
    assert pct(5, 10) == 0.5
    assert pct(0, 4) == 0.0


def test_format_minutes():
    assert format_minutes(1961) == "32:41"
    assert format_minutes(0) == "0:00"
    assert format_minutes(None) == "--"  # DNP, not zero


# --- box score endpoint ----------------------------------------------------


def test_boxscore_returns_teams_and_players(client):
    seed_boxscore(client.Session)
    r = client.get(f"/api/v1/games/{GID}/boxscore")
    assert r.status_code == 200
    body = r.json()

    assert body["nba_game_id"] == GID
    assert body["is_live"] is False
    assert body["home"]["abbreviation"] == "NYK"
    assert body["away"]["abbreviation"] == "DET"
    assert body["home"]["points"] == 110
    assert len(body["home"]["players"]) == 2
    assert len(body["away"]["players"]) == 1


def test_percentages_are_computed_not_stored(client):
    seed_boxscore(client.Session)
    body = client.get(f"/api/v1/games/{GID}/boxscore").json()

    brunson = body["home"]["players"][0]
    assert brunson["fgm"] == 16 and brunson["fga"] == 28
    assert brunson["fg_pct"] == round(16 / 28, 3)

    # Nothing in the stored model carries a percentage.
    stored = {c.name for c in PlayerGameStats.__table__.columns}
    assert not any("pct" in c for c in stored)


def test_rebounds_derived_from_the_split(client):
    seed_boxscore(client.Session)
    body = client.get(f"/api/v1/games/{GID}/boxscore").json()
    brunson = body["home"]["players"][0]
    assert brunson["oreb"] == 1 and brunson["dreb"] == 5
    assert brunson["rebounds"] == 6


def test_dnp_player_shows_dashes_not_zeroes(client):
    seed_boxscore(client.Session)
    body = client.get(f"/api/v1/games/{GID}/boxscore").json()
    bench = [p for p in body["home"]["players"] if p["full_name"] == "Bench Player"][0]
    assert bench["played"] is False
    assert bench["minutes"] == "--"
    assert bench["seconds_played"] is None
    assert bench["plus_minus"] is None
    assert bench["fg_pct"] is None


def test_players_sorted_starters_first_then_minutes(client):
    seed_boxscore(client.Session)
    body = client.get(f"/api/v1/games/{GID}/boxscore").json()
    home = body["home"]["players"]
    assert home[0]["started"] is True
    assert home[-1]["started"] is False


def test_team_rebounds_gap_is_visible_not_faked(client):
    """Seeded games have no team_rebounds; that shows as null, not 0."""
    seed_boxscore(client.Session)
    body = client.get(f"/api/v1/games/{GID}/boxscore").json()
    assert body["home"]["team_rebounds"] == 5
    assert body["away"]["team_rebounds"] is None


def test_boxscore_for_game_with_no_data_is_not_an_error(client):
    """A scheduled game has no box score — that's null, not 404."""
    r = client.get(f"/api/v1/games/{GID}/boxscore")
    assert r.status_code == 200
    assert r.json()["home"] is None


def test_boxscore_unknown_game_404s(client):
    assert client.get("/api/v1/games/0000000000/boxscore").status_code == 404


# --- win probability source handoff ----------------------------------------


def test_curve_uses_play_by_play_when_present(client):
    db = client.Session()
    for i in range(5):
        db.add(PlayByPlay(game_id=1, event_num=i, period=1,
                          clock=f"PT{11 - i:02d}M00.00S",
                          score_home=2 * i, score_away=i))
    db.commit()
    db.close()

    body = client.get(f"/api/v1/games/{GID}/win-probability").json()
    assert body["source"] == "play_by_play"
    assert len(body["points"]) == 5


def test_curve_falls_back_to_snapshots_for_a_live_game(client):
    """No play-by-play yet — the live game still gets a curve."""
    db = client.Session()
    base = datetime.now(timezone.utc)
    for i in range(3):
        db.add(GameStateSnapshot(game_id=1, period=2, clock=f"PT{10 - i:02d}M00.00S",
                                 score_home=40 + i * 3, score_away=38 + i,
                                 captured_at=base + timedelta(minutes=i)))
    db.commit()
    db.close()

    body = client.get(f"/api/v1/games/{GID}/win-probability").json()
    assert body["source"] == "snapshots"
    assert len(body["points"]) == 3


def test_play_by_play_wins_when_both_sources_exist(client):
    """
    After the seeder backfills a game that was polled live, the curve upgrades
    to the finer source instead of interleaving the two.
    """
    db = client.Session()
    db.add(GameStateSnapshot(game_id=1, period=2, clock="PT10M00.00S",
                             score_home=40, score_away=38,
                             captured_at=datetime.now(timezone.utc)))
    for i in range(10):
        db.add(PlayByPlay(game_id=1, event_num=i, period=1,
                          clock=f"PT{11 - i:02d}M00.00S",
                          score_home=2 * i, score_away=i))
    db.commit()
    db.close()

    body = client.get(f"/api/v1/games/{GID}/win-probability").json()
    assert body["source"] == "play_by_play"
    assert len(body["points"]) == 10  # not 11 — snapshots are not mixed in


def test_curve_with_no_data_returns_empty_not_error(client):
    body = client.get(f"/api/v1/games/{GID}/win-probability").json()
    assert body["source"] == "none"
    assert body["points"] == []


def test_curve_probabilities_are_within_range(client):
    db = client.Session()
    for i in range(20):
        db.add(PlayByPlay(game_id=1, event_num=i, period=(i // 5) + 1,
                          clock="PT06M00.00S", score_home=i * 3, score_away=i * 2))
    db.commit()
    db.close()

    body = client.get(f"/api/v1/games/{GID}/win-probability").json()
    assert all(0.0 <= p["home_win_probability"] <= 1.0 for p in body["points"])
    assert all(p["home_score"] >= p["away_score"] for p in body["points"])
