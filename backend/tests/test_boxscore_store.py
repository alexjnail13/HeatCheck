"""
Tests for the box score write path: conversion, identity resolution, upsert.

Runs against an in-memory SQLite database built from the real models, so the
unique constraints and foreign keys under test are the ones in production.

    python -m pytest tests/test_boxscore_store.py -v
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    Game,
    Player,
    PlayerExternalId,
    PlayerGameStats,
    Team,
    TeamExternalId,
    TeamGameStats,
)
from app.pipeline.seed_boxscores import (
    BoxScoreShapeError,
    convert_boxscore,
    dataset_to_rows,
    player_line_from_row,
)
from app.providers.nba_cdn import PlayerLine, TeamLine
from app.services.boxscore_store import (
    UnknownTeamError,
    resolve_player_id,
    resolve_team_id,
    store_boxscore,
)

PROVIDER = "nba"
HOME_NBA_ID = 1610612760  # OKC
AWAY_NBA_ID = 1610612747  # LAL


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add_all([
        Team(id=1, nba_team_id=HOME_NBA_ID, abbreviation="OKC",
             full_name="Oklahoma City Thunder", city="Oklahoma City", state="OK",
             conference="West", division="Northwest"),
        Team(id=2, nba_team_id=AWAY_NBA_ID, abbreviation="LAL",
             full_name="Los Angeles Lakers", city="Los Angeles", state="CA",
             conference="West", division="Pacific"),
    ])
    session.add(Game(
        id=1, nba_game_id="0042500222", season="2025-26",
        game_date=date(2026, 5, 7), home_team_id=1, away_team_id=2,
        home_team_score=110, away_team_score=104, status="Final",
        season_type="Playoffs",
    ))
    session.commit()
    yield session
    session.close()


def make_player_line(person_id="203507", team_id=str(HOME_NBA_ID), **kw) -> PlayerLine:
    defaults = dict(
        provider_player_id=person_id, provider_team_id=team_id,
        full_name="Shai Gilgeous-Alexander", first_name="Shai",
        last_name="Gilgeous-Alexander", position="G", jersey_number="2",
        started=True, seconds_played=1961, points=31, fgm=11, fga=22,
        fg3m=2, fg3a=5, ftm=7, fta=8, oreb=1, dreb=5, assists=6,
        steals=2, blocks=1, turnovers=3, fouls=2, plus_minus=8,
    )
    defaults.update(kw)
    return PlayerLine(**defaults)


def make_team_line(team_id=str(HOME_NBA_ID), is_home=True, **kw) -> TeamLine:
    defaults = dict(
        provider_team_id=team_id, tricode="OKC", is_home=is_home, points=110,
        fgm=40, fga=85, fg3m=14, fg3a=38, ftm=16, fta=20, oreb=9, dreb=34,
        assists=25, steals=8, blocks=5, turnovers=12, fouls=18,
        team_rebounds=4, team_turnovers=2,
    )
    defaults.update(kw)
    return TeamLine(**defaults)


# --- identity resolution ---------------------------------------------------


def test_resolve_team_falls_back_to_nba_team_id_and_records_mapping(db):
    """First lookup falls back to nba_team_id, then persists the mapping."""
    assert db.query(TeamExternalId).count() == 0

    team_id = resolve_team_id(db, PROVIDER, str(HOME_NBA_ID))
    assert team_id == 1

    mapping = db.query(TeamExternalId).one()
    assert (mapping.provider, mapping.provider_id) == (PROVIDER, str(HOME_NBA_ID))
    assert mapping.provider_abbreviation == "OKC"

    # Second call uses the mapping — no duplicate row.
    assert resolve_team_id(db, PROVIDER, str(HOME_NBA_ID)) == 1
    assert db.query(TeamExternalId).count() == 1


def test_resolve_team_unknown_raises_rather_than_skipping(db):
    """An untracked team must fail loudly, not silently drop half a box score."""
    with pytest.raises(UnknownTeamError, match="9999999"):
        resolve_team_id(db, PROVIDER, "9999999")


def test_resolve_player_creates_once_then_reuses(db):
    line = make_player_line()
    first = resolve_player_id(db, PROVIDER, line)
    db.commit()

    assert db.query(Player).count() == 1
    assert db.query(PlayerExternalId).count() == 1
    assert resolve_player_id(db, PROVIDER, line) == first
    assert db.query(Player).count() == 1


def test_player_identity_is_the_provider_id_not_the_name(db):
    """A renamed player is the same player; a namesake is not."""
    original = resolve_player_id(db, PROVIDER, make_player_line(person_id="203507"))
    db.commit()

    renamed = resolve_player_id(
        db, PROVIDER, make_player_line(person_id="203507", full_name="Shai Gilgeous")
    )
    assert renamed == original
    assert db.query(Player).count() == 1
    assert db.get(Player, original).full_name == "Shai Gilgeous"

    # Same name, different id => a different person.
    namesake = resolve_player_id(
        db, PROVIDER, make_player_line(person_id="999999", full_name="Shai Gilgeous")
    )
    assert namesake != original
    assert db.query(Player).count() == 2


# --- upsert ----------------------------------------------------------------


def test_store_boxscore_inserts(db):
    counts = store_boxscore(
        db, 1, PROVIDER,
        [make_team_line(), make_team_line(str(AWAY_NBA_ID), is_home=False, tricode="LAL")],
        [make_player_line(), make_player_line("2544", str(AWAY_NBA_ID), full_name="LeBron James")],
    )
    db.commit()

    assert counts["players_inserted"] == 2
    assert counts["teams_inserted"] == 2
    assert db.query(PlayerGameStats).count() == 2
    assert db.query(TeamGameStats).count() == 2


def test_reingesting_a_live_game_updates_rather_than_duplicates(db):
    """
    The core idempotency claim.

    A box score is cumulative totals, not events — polling at halftime and again
    at the buzzer are two measurements of one fact, so the row converges instead
    of duplicating.
    """
    halftime = make_player_line(points=14, seconds_played=900, fgm=5, fga=9)
    store_boxscore(db, 1, PROVIDER, [make_team_line(points=55)], [halftime])
    db.commit()
    assert db.query(PlayerGameStats).count() == 1
    assert db.query(PlayerGameStats).one().points == 14

    final = make_player_line(points=31, seconds_played=1961, fgm=11, fga=22)
    counts = store_boxscore(db, 1, PROVIDER, [make_team_line(points=110)], [final])
    db.commit()

    assert counts["players_inserted"] == 0
    assert counts["players_updated"] == 1
    row = db.query(PlayerGameStats).one()
    assert (row.points, row.seconds_played, row.fgm, row.fga) == (31, 1961, 11, 22)
    assert db.query(TeamGameStats).one().points == 110


def test_repeated_ingestion_is_stable(db):
    """Run the same final box score 5x — still one row per player."""
    lines = [make_player_line(), make_player_line("2544", str(AWAY_NBA_ID))]
    teams = [make_team_line(), make_team_line(str(AWAY_NBA_ID), is_home=False)]
    for _ in range(5):
        store_boxscore(db, 1, PROVIDER, teams, lines)
        db.commit()

    assert db.query(PlayerGameStats).count() == 2
    assert db.query(TeamGameStats).count() == 2
    assert db.query(Player).count() == 2


def test_dnp_player_keeps_null_minutes(db):
    store_boxscore(db, 1, PROVIDER, [], [
        make_player_line(seconds_played=None, started=False, points=0, plus_minus=None)
    ])
    db.commit()
    row = db.query(PlayerGameStats).one()
    assert row.seconds_played is None  # not 0
    assert row.plus_minus is None
    assert row.points == 0


def test_team_totals_are_stored_not_derived(db):
    """team_rebounds belongs to no player, so it can't come from summing rows."""
    store_boxscore(db, 1, PROVIDER, [make_team_line(team_rebounds=4, team_turnovers=2)],
                   [make_player_line(oreb=1, dreb=5)])
    db.commit()
    team_row = db.query(TeamGameStats).one()
    assert team_row.team_rebounds == 4
    assert team_row.oreb + team_row.dreb != 1 + 5


# --- nba_api conversion ----------------------------------------------------

PLAYER_ROW = {
    "gameId": "0042500222", "teamId": HOME_NBA_ID, "teamTricode": "OKC",
    "personId": 1628983, "firstName": "Shai", "familyName": "Gilgeous-Alexander",
    "nameI": "S. Gilgeous-Alexander", "position": "G", "jerseyNum": "2",
    "comment": "", "minutes": "32:41",
    "fieldGoalsMade": 11, "fieldGoalsAttempted": 22, "fieldGoalsPercentage": 0.5,
    "threePointersMade": 2, "threePointersAttempted": 5,
    "freeThrowsMade": 7, "freeThrowsAttempted": 8,
    "reboundsOffensive": 1, "reboundsDefensive": 5, "reboundsTotal": 6,
    "assists": 6, "steals": 2, "blocks": 1, "turnovers": 3,
    "foulsPersonal": 2, "points": 31, "plusMinusPoints": 8,
}

BENCH_ROW = {
    **PLAYER_ROW, "personId": 1630581, "firstName": "Bench", "familyName": "Guy",
    "position": "",  # empty position == did not start
    "minutes": "", "points": 0, "plusMinusPoints": None,
    "fieldGoalsMade": 0, "fieldGoalsAttempted": 0,
}

NORMALIZED = {
    "PlayerStats": [PLAYER_ROW, BENCH_ROW],
    "TeamStats": [
        {"teamId": HOME_NBA_ID, "teamTricode": "OKC", "points": 110,
         "fieldGoalsMade": 40, "fieldGoalsAttempted": 85, "reboundsOffensive": 9,
         "reboundsDefensive": 34, "assists": 25, "turnovers": 12, "foulsPersonal": 18},
        {"teamId": AWAY_NBA_ID, "teamTricode": "LAL", "points": 104,
         "fieldGoalsMade": 38, "fieldGoalsAttempted": 82, "reboundsOffensive": 8,
         "reboundsDefensive": 31, "assists": 22, "turnovers": 14, "foulsPersonal": 20},
    ],
    "TeamStarterBenchStats": [],
}


class _FakeDataSet:
    """Mimics nba_api's Endpoint.DataSet — headers + row arrays."""

    def __init__(self, data):
        self._data = data

    def get_dict(self):
        return self._data


def test_dataset_to_rows_zips_headers_with_data():
    """
    V3 endpoints return headers/data arrays, not resultSets — which is why
    get_normalized_dict() came back empty and the first seeder run failed.
    """
    ds = _FakeDataSet({
        "headers": ["gameId", "personId", "points"],
        "data": [["0042500222", 203507, 31], ["0042500222", 2544, 24]],
    })
    rows = dataset_to_rows(ds)
    assert rows == [
        {"gameId": "0042500222", "personId": 203507, "points": 31},
        {"gameId": "0042500222", "personId": 2544, "points": 24},
    ]


def test_dataset_to_rows_handles_empty_and_none():
    assert dataset_to_rows(None) == []
    assert dataset_to_rows(_FakeDataSet({})) == []
    assert dataset_to_rows(_FakeDataSet({"headers": [], "data": []})) == []
    assert dataset_to_rows(_FakeDataSet({"headers": ["a"], "data": []})) == []


def test_dataset_to_rows_rejects_multilevel_headers():
    ds = _FakeDataSet({"headers": [{"name": "level0"}], "data": [[1]]})
    with pytest.raises(BoxScoreShapeError, match="multi-level"):
        dataset_to_rows(ds)


def test_dataset_rows_feed_straight_into_conversion():
    """End-to-end: DataSet shape -> rows -> PlayerLine."""
    ds = _FakeDataSet({
        "headers": list(PLAYER_ROW.keys()),
        "data": [list(PLAYER_ROW.values())],
    })
    line = player_line_from_row(dataset_to_rows(ds)[0])
    assert line.points == 31
    assert line.seconds_played == 1961
    assert line.started is True


def test_minutes_string_format_parses():
    """stats.nba.com gives '32:41'; the CDN gives 'PT32M41.00S'. Same seconds."""
    assert player_line_from_row(PLAYER_ROW).seconds_played == 1961


def test_started_is_derived_from_position_not_row_order():
    assert player_line_from_row(PLAYER_ROW).started is True
    assert player_line_from_row(BENCH_ROW).started is False


def test_dnp_minutes_convert_to_none():
    assert player_line_from_row(BENCH_ROW).seconds_played is None
    assert player_line_from_row(BENCH_ROW).plus_minus is None


def test_convert_boxscore_uses_our_home_team_not_the_feeds_ordering():
    teams, players = convert_boxscore(NORMALIZED, home_nba_team_id=HOME_NBA_ID)
    assert len(players) == 2
    assert [t.is_home for t in teams] == [True, False]

    # Flip which team we consider home; the SAME payload must follow our record.
    teams_flipped, _ = convert_boxscore(NORMALIZED, home_nba_team_id=AWAY_NBA_ID)
    assert [t.is_home for t in teams_flipped] == [False, True]


def test_convert_boxscore_rejects_unrecognised_shape():
    with pytest.raises(BoxScoreShapeError, match="PlayerStats"):
        convert_boxscore({"SomethingElse": []}, home_nba_team_id=HOME_NBA_ID)


def test_convert_boxscore_rejects_ambiguous_home_team():
    """If our home id matches neither team, fail rather than store nonsense."""
    with pytest.raises(BoxScoreShapeError, match="expected exactly 1 home team"):
        convert_boxscore(NORMALIZED, home_nba_team_id=1610612739)


def test_end_to_end_convert_then_store(db):
    teams, players = convert_boxscore(NORMALIZED, home_nba_team_id=HOME_NBA_ID)
    store_boxscore(db, 1, PROVIDER, teams, players)
    db.commit()

    assert db.query(PlayerGameStats).count() == 2
    starter = (
        db.query(PlayerGameStats).join(Player).filter(Player.first_name == "Shai").one()
    )
    assert starter.points == 31
    assert starter.seconds_played == 1961
    assert starter.started is True
    assert starter.team_id == 1

    home = db.query(TeamGameStats).filter_by(is_home=True).one()
    assert home.points == 110 and home.team_id == 1
