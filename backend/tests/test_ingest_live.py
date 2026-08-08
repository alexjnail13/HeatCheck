"""
Tests for the live ingestion job.

The season is over, so there is no live feed to test against. These drive
ingest_game() with synthetic GameSummary/BoxScore objects instead, which is
enough to pin down the behaviour that matters: snapshots append, box scores
upsert, and a repeated poll doesn't duplicate anything.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    Game,
    GameExternalId,
    GameStateSnapshot,
    PlayerGameStats,
    Team,
    TeamGameStats,
)
from app.pipeline import ingest_live
from app.providers import nba_cdn
from app.providers.nba_cdn import BoxScore, GameSummary, PlayerLine, ProviderError, TeamLine
from app.services.boxscore_store import UnknownGameError, resolve_game_id

HOME_NBA_ID = 1610612760
AWAY_NBA_ID = 1610612747
GAME_ID = "0042500222"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        Team(id=1, nba_team_id=HOME_NBA_ID, abbreviation="OKC", full_name="Thunder",
             city="OKC", state="OK", conference="West", division="Northwest"),
        Team(id=2, nba_team_id=AWAY_NBA_ID, abbreviation="LAL", full_name="Lakers",
             city="LA", state="CA", conference="West", division="Pacific"),
    ])
    session.add(Game(
        id=1, nba_game_id=GAME_ID, season="2025-26", game_date=date(2026, 5, 7),
        home_team_id=1, away_team_id=2, status="Scheduled", season_type="Playoffs",
    ))
    session.commit()
    yield session
    session.close()


def summary(**kw) -> GameSummary:
    defaults = dict(
        provider_game_id=GAME_ID, status=nba_cdn.STATUS_LIVE, status_text="Q3 4:30",
        period=3, game_clock="PT04M30.00S", clock_seconds_remaining=270,
        tipoff_utc=datetime(2026, 5, 8, 1, 30, tzinfo=timezone.utc),
        is_neutral_site=False,
        home_provider_team_id=str(HOME_NBA_ID), home_tricode="OKC",
        home_score=78, home_timeouts_remaining=3,
        away_provider_team_id=str(AWAY_NBA_ID), away_tricode="LAL",
        away_score=74, away_timeouts_remaining=2,
    )
    defaults.update(kw)
    return GameSummary(**defaults)


def player(pid="203507", team=str(HOME_NBA_ID), **kw) -> PlayerLine:
    defaults = dict(
        provider_player_id=pid, provider_team_id=team, full_name="SGA",
        first_name="Shai", last_name="Gilgeous-Alexander", position="G",
        jersey_number="2", started=True, seconds_played=900, points=14,
        fgm=5, fga=9, fg3m=1, fg3a=3, ftm=3, fta=4, oreb=0, dreb=3,
        assists=4, steals=1, blocks=0, turnovers=2, fouls=1, plus_minus=5,
    )
    defaults.update(kw)
    return PlayerLine(**defaults)


def team_line(team=str(HOME_NBA_ID), is_home=True, **kw) -> TeamLine:
    defaults = dict(
        provider_team_id=team, tricode="OKC", is_home=is_home, points=78,
        fgm=28, fga=60, fg3m=8, fg3a=22, ftm=14, fta=18, oreb=6, dreb=22,
        assists=17, steals=5, blocks=3, turnovers=8, fouls=12,
        team_rebounds=3, team_turnovers=1,
    )
    defaults.update(kw)
    return TeamLine(**defaults)


def box(**kw) -> BoxScore:
    defaults = dict(
        provider_game_id=GAME_ID, status=nba_cdn.STATUS_LIVE, period=3,
        teams=[team_line()], players=[player()],
    )
    defaults.update(kw)
    return BoxScore(**defaults)


@pytest.fixture()
def no_boxscore(monkeypatch):
    monkeypatch.setattr(
        nba_cdn, "fetch_boxscore",
        lambda gid: (_ for _ in ()).throw(ProviderError("404 not published")),
    )


@pytest.fixture()
def with_boxscore(monkeypatch):
    monkeypatch.setattr(nba_cdn, "fetch_boxscore", lambda gid: box())


# --- game identity ---------------------------------------------------------


def test_resolve_game_falls_back_to_nba_game_id_and_records_mapping(db):
    assert db.query(GameExternalId).count() == 0
    assert resolve_game_id(db, "nba", GAME_ID) == 1

    mapping = db.query(GameExternalId).one()
    assert (mapping.provider, mapping.provider_id) == ("nba", GAME_ID)

    assert resolve_game_id(db, "nba", GAME_ID) == 1
    assert db.query(GameExternalId).count() == 1


def test_unknown_game_raises_rather_than_inventing_a_row(db):
    """A game we've never scheduled means a stale schedule, not a new game."""
    with pytest.raises(UnknownGameError, match="0099999999"):
        resolve_game_id(db, "nba", "0099999999")
    assert db.query(Game).count() == 1


# --- game row sync ---------------------------------------------------------


def test_ingest_updates_status_scores_and_backfills_tipoff(db, no_boxscore):
    game = db.get(Game, 1)
    assert game.status == "Scheduled" and game.tipoff_utc is None

    ingest_live.ingest_game(db, summary())
    db.commit()

    game = db.get(Game, 1)
    assert game.status == "Live"
    assert (game.home_team_score, game.away_team_score) == (78, 74)
    assert game.tipoff_utc is not None  # backfilled from the feed


def test_final_status_maps_to_our_existing_vocabulary(db, no_boxscore):
    ingest_live.ingest_game(db, summary(status=nba_cdn.STATUS_FINAL, status_text="Final"))
    db.commit()
    assert db.get(Game, 1).status == "Final"


# --- snapshots are append-only --------------------------------------------


def test_live_game_writes_a_snapshot(db, no_boxscore):
    result = ingest_live.ingest_game(db, summary())
    db.commit()

    assert result["snapshot"] is True
    snap = db.query(GameStateSnapshot).one()
    assert (snap.period, snap.score_home, snap.score_away) == (3, 78, 74)
    assert snap.clock == "PT04M30.00S"


def test_scheduled_game_writes_no_snapshot(db, no_boxscore):
    result = ingest_live.ingest_game(
        db, summary(status=nba_cdn.STATUS_SCHEDULED, period=0, game_clock="")
    )
    db.commit()
    assert result["snapshot"] is False
    assert db.query(GameStateSnapshot).count() == 0


def test_clock_advancing_appends_a_second_snapshot(db, no_boxscore):
    """Distinct moments accumulate — this is the curve the WP chart draws."""
    ingest_live.ingest_game(db, summary(game_clock="PT04M30.00S", home_score=78))
    db.commit()
    ingest_live.ingest_game(db, summary(game_clock="PT03M58.00S", home_score=81))
    db.commit()

    snaps = db.query(GameStateSnapshot).order_by(GameStateSnapshot.id).all()
    assert len(snaps) == 2
    assert [s.score_home for s in snaps] == [78, 81]


def test_identical_poll_does_not_duplicate_a_snapshot(db, no_boxscore):
    """
    An overlapping or retried cron run must not double-record one moment.
    UNIQUE(game_id, period, clock) absorbs it.
    """
    assert ingest_live.ingest_game(db, summary())["snapshot"] is True
    db.commit()
    assert ingest_live.ingest_game(db, summary())["snapshot"] is False
    db.commit()

    assert db.query(GameStateSnapshot).count() == 1


def test_snapshots_store_no_prediction(db, no_boxscore):
    """
    Raw state only. Win probability is computed fresh at read time, so
    retraining the model never strands old rows.
    """
    ingest_live.ingest_game(db, summary())
    db.commit()
    columns = {c.name for c in GameStateSnapshot.__table__.columns}
    assert not any(
        term in c for c in columns for term in ("prob", "prediction", "win_p")
    )


# --- box scores upsert -----------------------------------------------------


def test_live_boxscore_is_stored(db, with_boxscore):
    result = ingest_live.ingest_game(db, summary())
    db.commit()

    assert result["boxscore"]["players_inserted"] == 1
    assert db.query(PlayerGameStats).count() == 1
    assert db.query(TeamGameStats).count() == 1


def test_repeated_polls_upsert_boxscore_but_append_snapshots(db, monkeypatch):
    """
    The central distinction: cumulative totals converge, events accumulate.
    """
    monkeypatch.setattr(
        nba_cdn, "fetch_boxscore",
        lambda gid: box(players=[player(points=14, seconds_played=900)]),
    )
    ingest_live.ingest_game(db, summary(game_clock="PT04M30.00S"))
    db.commit()

    monkeypatch.setattr(
        nba_cdn, "fetch_boxscore",
        lambda gid: box(players=[player(points=31, seconds_played=1961)]),
    )
    ingest_live.ingest_game(db, summary(game_clock="PT00M12.00S", home_score=95))
    db.commit()

    # One player row, updated to the latest totals...
    row = db.query(PlayerGameStats).one()
    assert (row.points, row.seconds_played) == (31, 1961)
    # ...but two snapshots, because those are distinct moments.
    assert db.query(GameStateSnapshot).count() == 2


def test_missing_boxscore_file_is_not_an_error(db, no_boxscore):
    """A game that hasn't tipped off has no box score file. That's normal."""
    result = ingest_live.ingest_game(db, summary())
    db.commit()
    assert result["boxscore"] is None
    assert db.query(PlayerGameStats).count() == 0
    # The snapshot still got written.
    assert db.query(GameStateSnapshot).count() == 1


def test_run_once_handles_empty_offseason_scoreboard(monkeypatch):
    monkeypatch.setattr(nba_cdn, "fetch_scoreboard", lambda: [])
    assert ingest_live.run_once() == 0


def test_run_once_survives_a_dead_feed(monkeypatch):
    """A dead provider logs and exits non-zero — it never raises."""
    def boom():
        raise ProviderError("connection refused")

    monkeypatch.setattr(nba_cdn, "fetch_scoreboard", boom)
    assert ingest_live.run_once() == 1
