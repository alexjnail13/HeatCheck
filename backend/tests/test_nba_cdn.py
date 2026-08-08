"""
Tests for the cdn.nba.com parser.

The scoreboard fixture is a real (trimmed) response. The boxscore fixture is
built from the NBA live-boxscore shape and should be re-verified against a real
payload once a game is in progress — see scripts/dump_boxscore.py.

    python -m pytest tests/ -v
"""

import pytest

from app.providers import nba_cdn
from app.providers.nba_cdn import (
    ProviderDataError,
    parse_boxscore,
    parse_iso_duration_to_seconds,
    parse_scoreboard,
    parse_utc_timestamp,
)

# --- real trimmed scoreboard response -------------------------------------
SCOREBOARD_FIXTURE = {
    "meta": {"version": 1, "time": "2026-05-07 02:59:18.5918", "code": 200},
    "scoreboard": {
        "gameDate": "2026-05-07",
        "leagueId": "00",
        "games": [
            {
                "gameId": "0042500202",
                "gameCode": "20260507/CLEDET",
                "gameStatus": 1,
                "gameStatusText": "7:00 pm ET",
                "period": 0,
                "gameClock": "",
                "gameTimeUTC": "2026-05-07T23:00:00Z",
                "isNeutral": False,
                "homeTeam": {
                    "teamId": 1610612765,
                    "teamTricode": "DET",
                    "score": 0,
                    "timeoutsRemaining": 0,
                },
                "awayTeam": {
                    "teamId": 1610612739,
                    "teamTricode": "CLE",
                    "score": 0,
                    "timeoutsRemaining": 0,
                },
            },
            {
                "gameId": "0042500222",
                "gameStatus": 2,
                "gameStatusText": "Q3 4:30",
                "period": 3,
                "gameClock": "PT04M30.00S",
                "gameTimeUTC": "2026-05-08T01:30:00Z",
                "isNeutral": True,
                "homeTeam": {
                    "teamId": 1610612760,
                    "teamTricode": "OKC",
                    "score": 78,
                    "timeoutsRemaining": 3,
                },
                "awayTeam": {
                    "teamId": 1610612747,
                    "teamTricode": "LAL",
                    "score": 74,
                    "timeoutsRemaining": 2,
                },
            },
        ],
    },
}


def _player(person_id, name, **overrides):
    stats = {
        "assists": 5,
        "blocks": 1,
        "fieldGoalsAttempted": 15,
        "fieldGoalsMade": 7,
        "fieldGoalsPercentage": 0.4666,
        "foulsPersonal": 2,
        "freeThrowsAttempted": 4,
        "freeThrowsMade": 4,
        "minutes": "PT32M41.00S",
        "plusMinusPoints": 8,
        "points": 21,
        "reboundsDefensive": 6,
        "reboundsOffensive": 1,
        "reboundsTotal": 7,
        "steals": 2,
        "threePointersAttempted": 6,
        "threePointersMade": 3,
        "turnovers": 3,
    }
    stats.update(overrides.pop("statistics", {}))
    base = {
        "personId": person_id,
        "name": name,
        "firstName": name.split()[0],
        "familyName": name.split()[-1],
        "position": "F",
        "jerseyNum": "7",
        "starter": "1",
        "played": "1",
        "statistics": stats,
    }
    base.update(overrides)
    return base


BOXSCORE_FIXTURE = {
    "meta": {"version": 1, "code": 200},
    "game": {
        "gameId": "0042500222",
        "gameStatus": 2,
        "period": 3,
        "homeTeam": {
            "teamId": 1610612760,
            "teamTricode": "OKC",
            "players": [
                _player(203507, "Starter One"),
                _player(
                    1628983,
                    "Bench Two",
                    starter="0",
                    played="0",
                    statistics={"minutes": "", "points": 0, "plusMinusPoints": None},
                ),
            ],
            "statistics": {
                "points": 78,
                "fieldGoalsMade": 30,
                "fieldGoalsAttempted": 62,
                "threePointersMade": 10,
                "threePointersAttempted": 28,
                "freeThrowsMade": 8,
                "freeThrowsAttempted": 11,
                "reboundsOffensive": 9,
                "reboundsDefensive": 30,
                "reboundsTeam": 4,
                "assists": 20,
                "steals": 6,
                "blocks": 3,
                "turnovers": 11,
                "turnoversTeam": 2,
                "foulsPersonal": 15,
            },
        },
        "awayTeam": {
            "teamId": 1610612747,
            "teamTricode": "LAL",
            "players": [_player(2544, "Away Star")],
            "statistics": {
                "points": 74,
                "fieldGoalsMade": 28,
                "fieldGoalsAttempted": 60,
                "reboundsOffensive": 7,
                "reboundsDefensive": 28,
                "assists": 18,
                "turnovers": 9,
                "foulsPersonal": 14,
            },
        },
    },
}


# --- duration parsing ------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PT32M41.00S", 1961),  # the worked example: 32*60 + 41
        ("PT00M00.00S", 0),
        ("PT04M30.00S", 270),
        ("PT12M00.00S", 720),
        ("PT36M00.00S", 2160),
        ("PT1H05M00.00S", 3900),
        ("", None),
        (None, None),
        ("   ", None),
        ("garbage", None),
    ],
)
def test_parse_iso_duration(value, expected):
    assert parse_iso_duration_to_seconds(value) == expected


def test_minutes_precision_is_not_truncated():
    """32:41 must not collapse to 32 minutes — that error compounds per-minute."""
    assert parse_iso_duration_to_seconds("PT32M41.00S") == 1961
    assert parse_iso_duration_to_seconds("PT32M41.00S") != 32 * 60


def test_zero_seconds_differs_from_absent():
    """0 seconds played and 'did not play' are different facts."""
    assert parse_iso_duration_to_seconds("PT00M00.00S") == 0
    assert parse_iso_duration_to_seconds("") is None


def test_parse_utc_timestamp():
    ts = parse_utc_timestamp("2026-05-07T23:00:00Z")
    assert ts is not None
    assert (ts.year, ts.month, ts.day, ts.hour) == (2026, 5, 7, 23)
    assert ts.tzinfo is not None
    assert parse_utc_timestamp(None) is None
    assert parse_utc_timestamp("not a date") is None


# --- scoreboard ------------------------------------------------------------


def test_parse_scoreboard_basic():
    games = parse_scoreboard(SCOREBOARD_FIXTURE)
    assert len(games) == 2

    scheduled, live = games
    assert scheduled.provider_game_id == "0042500202"
    assert scheduled.status == nba_cdn.STATUS_SCHEDULED
    assert not scheduled.is_live
    assert scheduled.home_tricode == "DET"
    assert scheduled.away_tricode == "CLE"

    assert live.is_live
    assert live.period == 3
    assert live.clock_seconds_remaining == 270
    assert live.home_score == 78
    assert live.away_score == 74
    assert live.home_timeouts_remaining == 3


def test_home_and_away_come_from_named_keys_not_order():
    """
    The neutral-site regression guard.

    Home/away must be read from the homeTeam/awayTeam keys. A neutral-site game
    is flagged by the feed, and must NOT change which team we call home.
    """
    games = parse_scoreboard(SCOREBOARD_FIXTURE)
    neutral = games[1]
    assert neutral.is_neutral_site is True
    # Still unambiguous despite the neutral site.
    assert neutral.home_provider_team_id == "1610612760"
    assert neutral.away_provider_team_id == "1610612747"


def test_tipoff_is_parsed_as_utc():
    games = parse_scoreboard(SCOREBOARD_FIXTURE)
    tip = games[0].tipoff_utc
    assert tip is not None and tip.tzinfo is not None
    # 7:00pm ET on May 7 is 23:00 UTC the SAME day...
    assert (tip.month, tip.day, tip.hour) == (5, 7, 23)
    # ...but the 9:30pm ET game rolls over to May 8 in UTC. This is exactly why
    # game_date alone is not a safe cross-provider join key.
    late = games[1].tipoff_utc
    assert (late.month, late.day) == (5, 8)


def test_scoreboard_missing_required_field_raises():
    """
    A missing required field must raise, naming the field — never silently
    default. Validation order is homeTeam/awayTeam first, so a game stripped of
    everything reports the first missing field it hits.
    """
    payload = {"scoreboard": {"games": [{"gameStatus": 2}]}}
    with pytest.raises(ProviderDataError, match="homeTeam"):
        parse_scoreboard(payload)


def test_scoreboard_missing_game_id_raises():
    """gameId specifically — it's the join key, so it can never be defaulted."""
    payload = {
        "scoreboard": {
            "games": [
                {
                    "gameStatus": 2,
                    "homeTeam": {"teamId": 1, "teamTricode": "AAA"},
                    "awayTeam": {"teamId": 2, "teamTricode": "BBB"},
                }
            ]
        }
    }
    with pytest.raises(ProviderDataError, match="gameId"):
        parse_scoreboard(payload)


def test_scoreboard_missing_team_id_raises():
    """Team id is the other join key."""
    payload = {
        "scoreboard": {
            "games": [
                {
                    "gameId": "0022400001",
                    "gameStatus": 2,
                    "homeTeam": {"teamTricode": "AAA"},  # no teamId
                    "awayTeam": {"teamId": 2, "teamTricode": "BBB"},
                }
            ]
        }
    }
    with pytest.raises(ProviderDataError, match="teamId"):
        parse_scoreboard(payload)


def test_scoreboard_empty_offseason_is_not_an_error():
    """Out of season the feed serves an empty game list. That's normal."""
    assert parse_scoreboard({"scoreboard": {"games": []}}) == []
    assert parse_scoreboard({"scoreboard": {}}) == []


# --- box score -------------------------------------------------------------


def test_parse_boxscore_players():
    box = parse_boxscore(BOXSCORE_FIXTURE)
    assert box.provider_game_id == "0042500222"
    assert len(box.teams) == 2
    assert len(box.players) == 3  # 2 home + 1 away

    starter = box.players[0]
    assert starter.started is True  # "1" string -> True
    assert starter.seconds_played == 1961
    assert starter.points == 21
    assert starter.fgm == 7 and starter.fga == 15
    assert starter.oreb == 1 and starter.dreb == 6
    assert starter.plus_minus == 8
    assert starter.provider_team_id == "1610612760"


def test_dnp_player_has_null_minutes_not_zero():
    box = parse_boxscore(BOXSCORE_FIXTURE)
    dnp = box.players[1]
    assert dnp.started is False
    assert dnp.seconds_played is None  # NOT 0
    assert dnp.plus_minus is None  # NOT 0 — 0 is a real value


def test_no_percentage_fields_are_stored():
    """
    Percentages are derivable, so the parser must not surface them.
    Guards principle #3 against someone helpfully adding fg_pct later.
    """
    box = parse_boxscore(BOXSCORE_FIXTURE)
    fields = set(vars(box.players[0]))
    assert not any("pct" in f or "percent" in f.lower() for f in fields)
    # ...but the inputs needed to compute them are all present.
    assert {"fgm", "fga", "fg3m", "fg3a", "ftm", "fta"} <= fields


def test_team_totals_capture_non_player_stats():
    """team_rebounds/team_turnovers are why this table isn't derived."""
    box = parse_boxscore(BOXSCORE_FIXTURE)
    home = next(t for t in box.teams if t.is_home)
    assert home.points == 78
    assert home.team_rebounds == 4
    assert home.team_turnovers == 2

    player_oreb = sum(p.oreb for p in box.players if p.provider_team_id == "1610612760")
    player_dreb = sum(p.dreb for p in box.players if p.provider_team_id == "1610612760")
    # Proof the sum of player rows does NOT equal the team total.
    assert player_oreb + player_dreb != home.oreb + home.dreb


def test_team_totals_missing_optional_fields_are_none():
    box = parse_boxscore(BOXSCORE_FIXTURE)
    away = next(t for t in box.teams if not t.is_home)
    assert away.team_rebounds is None  # absent in fixture -> None, not 0
    assert away.is_home is False


def test_boxscore_home_away_flagged_correctly():
    box = parse_boxscore(BOXSCORE_FIXTURE)
    assert [t.is_home for t in box.teams] == [True, False]
    assert next(t for t in box.teams if t.is_home).tricode == "OKC"


def test_boxscore_missing_game_key_raises():
    with pytest.raises(ProviderDataError, match="game"):
        parse_boxscore({"meta": {}})
