"""
Persistence for box scores — the single write path for player and team stats.

Both ingestion routes land here:

    stats.nba.com  --(seed_boxscores.py)--\
                                           >-- PlayerLine/TeamLine --> this module
    cdn.nba.com    --(ingest_live.py)-----/

Because both convert to the same provider-neutral dataclasses first, there is
exactly one place that knows how box score data is stored, and swapping in
MySportsFeeds later touches neither this module nor the models.

Everything here is an UPSERT. A box score is a snapshot of cumulative totals,
not a stream of events: polling at halftime and again at the buzzer are two
measurements of one fact, so the later one overwrites the earlier. (Contrast
game_state_snapshots and play_by_play, which are event time series and are
append-only.) That also makes every job idempotent — re-run it fifty times and
you still get one row per player per game.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.database.models import (
    Game,
    GameExternalId,
    Player,
    PlayerExternalId,
    PlayerGameStats,
    Team,
    TeamExternalId,
    TeamGameStats,
)
from app.providers.nba_cdn import PlayerLine, TeamLine

logger = logging.getLogger(__name__)


class UnknownTeamError(LookupError):
    """
    A provider team id that maps to no team in our database.

    Raised rather than skipped: silently dropping a team means a box score with
    one side missing, which looks like a data bug months later. All-Star and
    international squads are filtered out before we get here.
    """


class UnknownGameError(LookupError):
    """A provider game id that maps to no game in our database."""


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


def resolve_team_id(db: Session, provider: str, provider_team_id: str) -> int:
    """
    Map a provider's team id to teams.id, via team_external_ids.

    Falls back to teams.nba_team_id when no mapping row exists yet and the
    provider is the NBA's own id space — and writes the mapping so the fallback
    only ever happens once per team.
    """
    mapping = (
        db.query(TeamExternalId)
        .filter(
            TeamExternalId.provider == provider,
            TeamExternalId.provider_id == str(provider_team_id),
        )
        .first()
    )
    if mapping:
        return mapping.team_id

    if provider == "nba":
        team = db.query(Team).filter(Team.nba_team_id == int(provider_team_id)).first()
        if team:
            db.add(
                TeamExternalId(
                    team_id=team.id,
                    provider=provider,
                    provider_id=str(provider_team_id),
                    provider_abbreviation=team.abbreviation,
                )
            )
            db.flush()
            return team.id

    raise UnknownTeamError(
        f"no team for provider={provider!r} provider_id={provider_team_id!r}"
    )


def resolve_game_id(db: Session, provider: str, provider_game_id: str) -> int:
    """
    Map a provider's game id to games.id, via game_external_ids.

    Falls back to games.nba_game_id for the NBA's own id space, then records the
    mapping. cdn.nba.com and stats.nba.com publish identical game ids, so a game
    seeded from one resolves to the same row when polled from the other — which
    is what lets the live job and the seeder converge instead of conflict.

    Raises rather than creating a game: the games table is populated by
    fetch_games.py from the season schedule. A provider game we've never heard
    of means the schedule is stale, and inventing a row would hide that.
    """
    mapping = (
        db.query(GameExternalId)
        .filter(
            GameExternalId.provider == provider,
            GameExternalId.provider_id == str(provider_game_id),
        )
        .first()
    )
    if mapping:
        return mapping.game_id

    if provider == "nba":
        game = db.query(Game).filter(Game.nba_game_id == str(provider_game_id)).first()
        if game:
            db.add(
                GameExternalId(
                    game_id=game.id,
                    provider=provider,
                    provider_id=str(provider_game_id),
                )
            )
            db.flush()
            return game.id

    raise UnknownGameError(
        f"no game for provider={provider!r} provider_id={provider_game_id!r} "
        f"— is the schedule seeded for this season?"
    )


def resolve_player_id(db: Session, provider: str, line: PlayerLine) -> int:
    """
    Map a provider's player id to players.id, creating the player if new.

    Player identity is keyed on the provider id, never on name: names are not
    unique (there have been two Jaylen Browns) and they change (marriages, legal
    name changes, transliteration fixes). The id is stable; the name is a label.
    """
    mapping = (
        db.query(PlayerExternalId)
        .filter(
            PlayerExternalId.provider == provider,
            PlayerExternalId.provider_id == str(line.provider_player_id),
        )
        .first()
    )
    if mapping:
        # Keep the display name current without touching identity.
        player = db.get(Player, mapping.player_id)
        if player and line.full_name and player.full_name != line.full_name:
            player.full_name = line.full_name
        return mapping.player_id

    player = Player(
        full_name=line.full_name or f"Unknown {line.provider_player_id}",
        first_name=line.first_name,
        last_name=line.last_name,
        position=line.position,
        jersey_number=line.jersey_number,
    )
    db.add(player)
    db.flush()  # assign player.id without committing

    db.add(
        PlayerExternalId(
            player_id=player.id,
            provider=provider,
            provider_id=str(line.provider_player_id),
        )
    )
    db.flush()
    return player.id


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------

_PLAYER_STAT_FIELDS = (
    "seconds_played", "started", "points", "fgm", "fga", "fg3m", "fg3a",
    "ftm", "fta", "oreb", "dreb", "assists", "steals", "blocks",
    "turnovers", "fouls", "plus_minus",
)

_TEAM_STAT_FIELDS = (
    "is_home", "points", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
    "oreb", "dreb", "assists", "steals", "blocks", "turnovers", "fouls",
    "team_rebounds", "team_turnovers",
)


def upsert_player_stats(
    db: Session, game_id: int, provider: str, lines: list[PlayerLine]
) -> tuple[int, int]:
    """
    Insert or update one game's player rows. Returns (inserted, updated).

    Existing rows for the game are loaded once and matched in memory rather than
    queried per player — one round trip instead of thirty.
    """
    existing = {
        row.player_id: row
        for row in db.query(PlayerGameStats).filter(PlayerGameStats.game_id == game_id)
    }

    inserted = updated = 0
    for line in lines:
        team_id = resolve_team_id(db, provider, line.provider_team_id)
        player_id = resolve_player_id(db, provider, line)

        row = existing.get(player_id)
        if row is None:
            row = PlayerGameStats(
                game_id=game_id, player_id=player_id, team_id=team_id
            )
            db.add(row)
            existing[player_id] = row
            inserted += 1
        else:
            # team_id can legitimately change if a mid-game correction lands.
            row.team_id = team_id
            updated += 1

        for field_name in _PLAYER_STAT_FIELDS:
            setattr(row, field_name, getattr(line, field_name))

    return inserted, updated


def upsert_team_stats(
    db: Session, game_id: int, provider: str, lines: list[TeamLine]
) -> tuple[int, int]:
    """Insert or update one game's team totals. Returns (inserted, updated)."""
    existing = {
        row.team_id: row
        for row in db.query(TeamGameStats).filter(TeamGameStats.game_id == game_id)
    }

    inserted = updated = 0
    for line in lines:
        team_id = resolve_team_id(db, provider, line.provider_team_id)

        row = existing.get(team_id)
        if row is None:
            row = TeamGameStats(game_id=game_id, team_id=team_id)
            db.add(row)
            existing[team_id] = row
            inserted += 1
        else:
            updated += 1

        for field_name in _TEAM_STAT_FIELDS:
            setattr(row, field_name, getattr(line, field_name))

    return inserted, updated


def store_boxscore(
    db: Session,
    game_id: int,
    provider: str,
    team_lines: list[TeamLine],
    player_lines: list[PlayerLine],
) -> dict[str, int]:
    """
    Store a full box score for one game. Caller owns the commit.

    Leaving the commit to the caller lets the seeder commit per game (so an
    interruption loses at most one game) while the live job can batch.
    """
    t_ins, t_upd = upsert_team_stats(db, game_id, provider, team_lines)
    p_ins, p_upd = upsert_player_stats(db, game_id, provider, player_lines)
    return {
        "teams_inserted": t_ins,
        "teams_updated": t_upd,
        "players_inserted": p_ins,
        "players_updated": p_upd,
    }
