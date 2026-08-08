"""
Seed player and team box scores from nba_api (stats.nba.com).

Why this exists separately from the live job: cdn.nba.com only publishes a
game's box score around game time and purges it afterwards, so it cannot
backfill history. stats.nba.com has the full archive but blocks datacenter IPs,
which is why this runs from your laptop — the same split seed_pbp.py already
uses for play-by-play.

    stats.nba.com  --(this file)------\
                                       >-- PlayerLine/TeamLine --> boxscore_store
    cdn.nba.com    --(ingest_live)----/

Both paths produce the SAME provider-neutral dataclasses and share one write
path, so a game seeded here and later polled live converges onto one row
instead of conflicting.

Run from your laptop, with DATABASE_URL pointed at the database you want filled:

    $env:DATABASE_URL="<External Database URL>"
    python -m app.pipeline.seed_boxscores --limit 3   # try a handful FIRST
    python -m app.pipeline.seed_boxscores             # then all final games
    python -m app.pipeline.seed_boxscores --season 2024-25
    python -m app.pipeline.seed_boxscores --refresh   # re-fetch already-seeded

Idempotent: seeded games are skipped by default, and re-seeding upserts rather
than duplicating, so an interrupted run just needs re-running.
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any

from nba_api.stats.endpoints import boxscoretraditionalv3

from app.database.models import Game, PlayerGameStats, Team
from app.database.session import SessionLocal, describe_database
from app.providers.durations import parse_duration_to_seconds
from app.providers.nba_cdn import PROVIDER, PlayerLine, TeamLine
from app.services.boxscore_store import UnknownTeamError, store_boxscore

REQUEST_DELAY = 1.5  # be polite to stats.nba.com
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Result-set names in the BoxScoreTraditionalV3 response. We look these up BY
# NAME rather than taking get_data_frames()[0] and [1], because frame order is
# an implementation detail of the endpoint and a reordered response would
# silently swap player rows for team rows. Same rule that fixed the neutral-site
# bug: read the structure, don't count on position.
PLAYER_RESULT_SET = "PlayerStats"
TEAM_RESULT_SET = "TeamStats"


def dataset_to_rows(dataset) -> list[dict]:
    """
    Turn an nba_api DataSet into a list of {column: value} dicts.

    V3 endpoints do NOT populate the `resultSets` structure that
    Endpoint.get_normalized_dict() parses — calling it returns {}. The V3 class
    instead exposes named DataSet attributes (`player_stats`, `team_stats`),
    each holding {"headers": [...], "data": [[...]]}. Zipping those gives us the
    same row dicts without a pandas round trip.
    """
    if dataset is None:
        return []
    raw = dataset.get_dict() or {}
    headers = raw.get("headers") or []
    rows = raw.get("data") or []
    # Multi-level headers (dicts rather than strings) appear on some endpoints;
    # BoxScoreTraditionalV3 isn't one of them, so bail loudly if we see them.
    if headers and not isinstance(headers[0], str):
        raise BoxScoreShapeError("multi-level headers not supported for box scores")
    return [dict(zip(headers, row)) for row in rows]


class BoxScoreShapeError(RuntimeError):
    """The endpoint returned a payload we don't recognise."""


# ---------------------------------------------------------------------------
# nba_api row -> provider-neutral dataclass
# ---------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    if value is None or value == "":
        return True
    # NaN is the only value that isn't equal to itself.
    return isinstance(value, float) and value != value


def _int(row: dict, key: str, default: int = 0) -> int:
    """Read an integer stat, treating NaN/None/'' as the default."""
    value = row.get(key)
    if _is_blank(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _opt_int(row: dict, key: str) -> int | None:
    """Read an integer that is meaningfully nullable (0 is a real value)."""
    value = row.get(key)
    if _is_blank(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _str(row: dict, key: str) -> str | None:
    value = row.get(key)
    if _is_blank(value):
        return None
    return str(value).strip() or None


def player_line_from_row(row: dict) -> PlayerLine:
    """
    Convert one BoxScoreTraditionalV3 player row into a PlayerLine.

    `started` is derived from the `position` column: V3 gives starters a real
    position ("F", "C", "G") and leaves it empty for bench players. The rows do
    happen to arrive starters-first, but relying on that ordering is the same
    positional assumption we refuse to make anywhere else.
    """
    position = _str(row, "position")
    first = _str(row, "firstName")
    family = _str(row, "familyName")
    full_name = " ".join(p for p in (first, family) if p) or _str(row, "nameI") or ""

    return PlayerLine(
        provider_player_id=str(_int(row, "personId")),
        provider_team_id=str(_int(row, "teamId")),
        full_name=full_name,
        first_name=first,
        last_name=family,
        position=position,
        jersey_number=_str(row, "jerseyNum"),
        started=bool(position),
        # None for a DNP (blank minutes), 0 only for an actual zero.
        seconds_played=parse_duration_to_seconds(_str(row, "minutes")),
        points=_int(row, "points"),
        fgm=_int(row, "fieldGoalsMade"),
        fga=_int(row, "fieldGoalsAttempted"),
        fg3m=_int(row, "threePointersMade"),
        fg3a=_int(row, "threePointersAttempted"),
        ftm=_int(row, "freeThrowsMade"),
        fta=_int(row, "freeThrowsAttempted"),
        oreb=_int(row, "reboundsOffensive"),
        dreb=_int(row, "reboundsDefensive"),
        assists=_int(row, "assists"),
        steals=_int(row, "steals"),
        blocks=_int(row, "blocks"),
        turnovers=_int(row, "turnovers"),
        fouls=_int(row, "foulsPersonal"),
        plus_minus=_opt_int(row, "plusMinusPoints"),
    )


def team_line_from_row(row: dict, *, is_home: bool) -> TeamLine:
    """Convert one BoxScoreTraditionalV3 team row into a TeamLine."""
    return TeamLine(
        provider_team_id=str(_int(row, "teamId")),
        tricode=_str(row, "teamTricode") or "",
        is_home=is_home,
        points=_int(row, "points"),
        fgm=_int(row, "fieldGoalsMade"),
        fga=_int(row, "fieldGoalsAttempted"),
        fg3m=_int(row, "threePointersMade"),
        fg3a=_int(row, "threePointersAttempted"),
        ftm=_int(row, "freeThrowsMade"),
        fta=_int(row, "freeThrowsAttempted"),
        oreb=_int(row, "reboundsOffensive"),
        dreb=_int(row, "reboundsDefensive"),
        assists=_int(row, "assists"),
        steals=_int(row, "steals"),
        blocks=_int(row, "blocks"),
        turnovers=_int(row, "turnovers"),
        fouls=_int(row, "foulsPersonal"),
        # V3's team row doesn't break these out; the live CDN feed does. Left
        # None rather than guessed — a known gap beats a wrong number.
        team_rebounds=None,
        team_turnovers=None,
    )


def convert_boxscore(
    payload: dict, home_nba_team_id: int
) -> tuple[list[TeamLine], list[PlayerLine]]:
    """
    Convert a normalised BoxScoreTraditionalV3 payload into our dataclasses.

    `home_nba_team_id` comes from OUR games row, not from the response. We
    already know who was home; re-deriving it from the feed's ordering would
    reintroduce exactly the bug that dropped the NBA Cup games.

    Split out from the network call so it can be tested against a fixture.
    """
    if PLAYER_RESULT_SET not in payload or TEAM_RESULT_SET not in payload:
        raise BoxScoreShapeError(
            f"expected result sets {PLAYER_RESULT_SET!r} and {TEAM_RESULT_SET!r}, "
            f"got {sorted(payload)}"
        )

    player_lines = [player_line_from_row(row) for row in payload[PLAYER_RESULT_SET]]
    team_lines = [
        team_line_from_row(row, is_home=(_int(row, "teamId") == home_nba_team_id))
        for row in payload[TEAM_RESULT_SET]
    ]

    home_count = sum(1 for t in team_lines if t.is_home)
    if team_lines and home_count != 1:
        raise BoxScoreShapeError(
            f"expected exactly 1 home team, found {home_count} "
            f"(home_nba_team_id={home_nba_team_id}, "
            f"teams={[t.provider_team_id for t in team_lines]})"
        )

    return team_lines, player_lines


def fetch_game_lines(
    game: Game, home_nba_team_id: int
) -> tuple[list[TeamLine], list[PlayerLine]]:
    """
    Fetch one game's box score from stats.nba.com and convert it.

    Reads the endpoint's NAMED data sets rather than get_data_frames()[0]/[1] —
    positional access would silently swap player and team rows if the endpoint
    ever reordered them.
    """
    box = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game.nba_game_id)
    payload = {
        PLAYER_RESULT_SET: dataset_to_rows(box.player_stats),
        TEAM_RESULT_SET: dataset_to_rows(box.team_stats),
    }
    return convert_boxscore(payload, home_nba_team_id)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def seed(
    *, season: str | None = None, limit: int | None = None, refresh: bool = False
) -> None:
    logger.info("Target database: %s", describe_database())

    db = SessionLocal()
    try:
        query = db.query(Game).filter(Game.status == "Final")
        if season:
            query = query.filter(Game.season == season)
        games = query.order_by(Game.game_date.desc()).all()

        if refresh:
            todo = games
        else:
            already = {
                gid for (gid,) in db.query(PlayerGameStats.game_id).distinct().all()
            }
            todo = [g for g in games if g.id not in already]
            logger.info("%d already seeded", len(already))

        if limit:
            todo = todo[:limit]

        logger.info("%d final games, %d to process", len(games), len(todo))

        # teams.id -> nba_team_id, so we can tell the converter who was home
        # without a per-game query.
        home_ids = {t.id: t.nba_team_id for t in db.query(Team).all()}

        succeeded = failed = 0
        for i, game in enumerate(todo, start=1):
            try:
                home_nba_team_id = home_ids.get(game.home_team_id)
                if home_nba_team_id is None:
                    raise UnknownTeamError(
                        f"home_team_id {game.home_team_id} not in teams table"
                    )

                team_lines, player_lines = fetch_game_lines(game, home_nba_team_id)
                if not player_lines:
                    logger.warning(
                        "[%d/%d] %s: empty box score, skipping",
                        i, len(todo), game.nba_game_id,
                    )
                    continue

                counts = store_boxscore(db, game.id, PROVIDER, team_lines, player_lines)
                # Commit per game: an interruption loses at most one game.
                db.commit()
                succeeded += 1
                logger.info(
                    "[%d/%d] %s: %d players (+%d/~%d), %d teams (+%d/~%d)",
                    i, len(todo), game.nba_game_id, len(player_lines),
                    counts["players_inserted"], counts["players_updated"],
                    len(team_lines),
                    counts["teams_inserted"], counts["teams_updated"],
                )
            except (UnknownTeamError, BoxScoreShapeError) as exc:
                db.rollback()
                failed += 1
                logger.error("[%d/%d] %s: %s", i, len(todo), game.nba_game_id, exc)
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.error(
                    "[%d/%d] %s: %s: %s",
                    i, len(todo), game.nba_game_id, type(exc).__name__, exc,
                )

            time.sleep(REQUEST_DELAY)

        logger.info("Done. %d succeeded, %d failed.", succeeded, failed)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", help='e.g. "2024-25"')
    parser.add_argument("--limit", type=int, help="process at most N games")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-fetch games already seeded (upserts, so it's safe)",
    )
    args = parser.parse_args()
    seed(season=args.season, limit=args.limit, refresh=args.refresh)


if __name__ == "__main__":
    main()
