"""
cdn.nba.com provider — live scoreboard and box scores.

Why this host: stats.nba.com rejects datacenter IPs, which is what broke the
live feed on Render. cdn.nba.com is a separate, S3-backed CDN with no auth and
no API key, and it publishes the same live data the NBA's own scoreboard uses.

Why it returns dataclasses instead of dicts: the ingestion job should never
learn a provider's field names. Swapping to MySportsFeeds means writing a new
module here that returns these same dataclasses, and changing nothing else.

Two behaviours worth knowing about this feed:
  * Out of season the scoreboard file stops regenerating and serves the last
    one produced, indefinitely. Stale content is NORMAL, not an error.
  * A boxscore file does not exist until a game tips off. A 403/404 for a
    scheduled game is expected, not a failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from app.providers.durations import parse_duration_to_seconds

logger = logging.getLogger(__name__)

# Provider slug stored in the *_external_ids tables.
#
# Deliberately "nba", not "nba_cdn": cdn.nba.com and stats.nba.com publish the
# SAME id space (game 0042500201 and person 2544 mean the same thing on both).
# They are two endpoints onto one provider's identifiers, so they share one slug
# and a game seeded from stats.nba.com resolves to the same row as the same game
# polled live from the CDN.
PROVIDER = "nba"

SCOREBOARD_URL = (
    "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
)
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"

TIMEOUT_SECONDS = 15

# These files are public and unauthenticated, but they sit behind a CDN filter
# that rejects requests which don't look like a browser fetching them from
# nba.com. A User-Agent of "python-requests" gets a 403 before the request ever
# reaches the file. Sending the headers a browser would send is what makes the
# same public URL return the same public JSON.
#
# This does NOT get past an IP-level block. If a 403 persists with these headers,
# the host itself is refusing the network you're calling from, and the fix is to
# call from somewhere else (see scripts/check_nba_cdn.py).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "Connection": "keep-alive",
}

# NBA game status codes, from the feed itself.
STATUS_SCHEDULED = 1
STATUS_LIVE = 2
STATUS_FINAL = 3


class ProviderError(RuntimeError):
    """Raised when the provider is unreachable or returns something unusable."""


class ProviderDataError(ProviderError):
    """
    Raised when the payload is reachable but missing a field we require.

    Deliberately distinct from a network error: a missing field means the feed's
    shape changed and the parser needs updating, which is a code problem, not a
    retry-later problem.
    """


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# The CDN uses ISO-8601 ("PT32M41.00S") for both the game clock and minutes
# played; the shared parser also handles the "32:41" that stats.nba.com returns.
parse_iso_duration_to_seconds = parse_duration_to_seconds


def parse_utc_timestamp(value: str | None) -> datetime | None:
    """Parse the feed's '2026-05-07T23:00:00Z' into an aware UTC datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        logger.warning("Unparseable timestamp %r", value)
        return None


def _require(payload: dict, key: str, context: str):
    """
    Fetch a required key, failing loudly with context.

    Using payload.get(key, 0) everywhere is how a feed change becomes a season
    of silently-zeroed stats. If a field we depend on disappears, we want a
    traceback naming it, not a plausible-looking wrong number.
    """
    if key not in payload:
        raise ProviderDataError(f"{context}: missing required field {key!r}")
    return payload[key]


# ---------------------------------------------------------------------------
# Return types — provider-neutral by design
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GameSummary:
    """A game as it appears on the live scoreboard."""

    provider_game_id: str
    status: int  # 1 scheduled, 2 live, 3 final
    status_text: str
    period: int
    game_clock: str | None
    clock_seconds_remaining: int | None
    tipoff_utc: datetime | None
    is_neutral_site: bool
    home_provider_team_id: str
    home_tricode: str
    home_score: int
    home_timeouts_remaining: int | None
    away_provider_team_id: str
    away_tricode: str
    away_score: int
    away_timeouts_remaining: int | None

    @property
    def is_live(self) -> bool:
        return self.status == STATUS_LIVE

    @property
    def is_final(self) -> bool:
        return self.status == STATUS_FINAL


@dataclass(frozen=True)
class PlayerLine:
    """One player's line in a box score. Raw counts only — no percentages."""

    provider_player_id: str
    provider_team_id: str
    full_name: str
    first_name: str | None
    last_name: str | None
    position: str | None
    jersey_number: str | None
    started: bool
    seconds_played: int | None
    points: int
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    plus_minus: int | None


@dataclass(frozen=True)
class TeamLine:
    """A team's totals. Not the sum of its player lines — see TeamGameStats."""

    provider_team_id: str
    tricode: str
    is_home: bool
    points: int
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    team_rebounds: int | None
    team_turnovers: int | None


@dataclass(frozen=True)
class BoxScore:
    provider_game_id: str
    status: int
    period: int
    teams: list[TeamLine] = field(default_factory=list)
    players: list[PlayerLine] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _get_json(url: str) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise ProviderError(f"{PROVIDER}: request failed for {url}: {exc}") from exc

    if resp.status_code == 403:
        # A 403 here is ambiguous and the two causes need different fixes, so
        # include the body: an Akamai/CDN denial page means the NETWORK is
        # blocked, while a short/empty body usually means the file just isn't
        # published (a game that hasn't tipped off).
        body = (resp.text or "")[:300].replace("\n", " ")
        raise ProviderError(
            f"{PROVIDER}: 403 for {url} "
            f"(network blocked, or file not published) body={body!r}"
        )
    if resp.status_code == 404:
        raise ProviderError(f"{PROVIDER}: 404 for {url} (not published yet)")
    if resp.status_code != 200:
        raise ProviderError(f"{PROVIDER}: HTTP {resp.status_code} for {url}")
    if not resp.content:
        raise ProviderError(f"{PROVIDER}: empty body for {url}")

    try:
        return resp.json()
    except ValueError as exc:
        raise ProviderError(f"{PROVIDER}: non-JSON response from {url}") from exc


# ---------------------------------------------------------------------------
# Scoreboard
# ---------------------------------------------------------------------------


def parse_scoreboard(payload: dict) -> list[GameSummary]:
    """Parse a todaysScoreboard payload into GameSummary objects."""
    scoreboard = _require(payload, "scoreboard", "scoreboard payload")
    games = scoreboard.get("games") or []

    summaries: list[GameSummary] = []
    for raw in games:
        ctx = f"game {raw.get('gameId', '?')}"
        # home/away come from named keys, never row order — the neutral-site
        # bug came from positional assumptions.
        home = _require(raw, "homeTeam", ctx)
        away = _require(raw, "awayTeam", ctx)
        clock = raw.get("gameClock") or None

        summaries.append(
            GameSummary(
                provider_game_id=str(_require(raw, "gameId", ctx)),
                status=int(_require(raw, "gameStatus", ctx)),
                status_text=raw.get("gameStatusText", ""),
                period=int(raw.get("period", 0)),
                game_clock=clock,
                clock_seconds_remaining=parse_iso_duration_to_seconds(clock),
                tipoff_utc=parse_utc_timestamp(raw.get("gameTimeUTC")),
                # The feed states this outright, so we never infer it.
                is_neutral_site=bool(raw.get("isNeutral", False)),
                home_provider_team_id=str(_require(home, "teamId", ctx + " homeTeam")),
                home_tricode=home.get("teamTricode", ""),
                home_score=int(home.get("score") or 0),
                home_timeouts_remaining=home.get("timeoutsRemaining"),
                away_provider_team_id=str(_require(away, "teamId", ctx + " awayTeam")),
                away_tricode=away.get("teamTricode", ""),
                away_score=int(away.get("score") or 0),
                away_timeouts_remaining=away.get("timeoutsRemaining"),
            )
        )
    return summaries


def fetch_scoreboard() -> list[GameSummary]:
    """Fetch today's scoreboard. Raises ProviderError if unreachable."""
    return parse_scoreboard(_get_json(SCOREBOARD_URL))


# ---------------------------------------------------------------------------
# Box score
# ---------------------------------------------------------------------------


def _stat(stats: dict, key: str, default: int = 0) -> int:
    value = stats.get(key, default)
    return default if value is None else int(value)


def _parse_player(raw: dict, provider_team_id: str) -> PlayerLine:
    ctx = f"player {raw.get('personId', '?')}"
    stats = raw.get("statistics") or {}

    # "starter"/"played" arrive as the strings "1"/"0", not booleans.
    started = str(raw.get("starter", "0")) == "1"

    return PlayerLine(
        provider_player_id=str(_require(raw, "personId", ctx)),
        provider_team_id=provider_team_id,
        full_name=raw.get("name") or "",
        first_name=raw.get("firstName"),
        last_name=raw.get("familyName"),
        position=raw.get("position") or None,
        jersey_number=raw.get("jerseyNum") or None,
        started=started,
        seconds_played=parse_iso_duration_to_seconds(stats.get("minutes")),
        points=_stat(stats, "points"),
        fgm=_stat(stats, "fieldGoalsMade"),
        fga=_stat(stats, "fieldGoalsAttempted"),
        fg3m=_stat(stats, "threePointersMade"),
        fg3a=_stat(stats, "threePointersAttempted"),
        ftm=_stat(stats, "freeThrowsMade"),
        fta=_stat(stats, "freeThrowsAttempted"),
        oreb=_stat(stats, "reboundsOffensive"),
        dreb=_stat(stats, "reboundsDefensive"),
        assists=_stat(stats, "assists"),
        steals=_stat(stats, "steals"),
        blocks=_stat(stats, "blocks"),
        turnovers=_stat(stats, "turnovers"),
        fouls=_stat(stats, "foulsPersonal"),
        # None, not 0: 0 is a real plus/minus value.
        plus_minus=(
            int(stats["plusMinusPoints"])
            if stats.get("plusMinusPoints") is not None
            else None
        ),
    )


def _parse_team(raw: dict, is_home: bool) -> TeamLine:
    ctx = f"team {raw.get('teamId', '?')}"
    stats = raw.get("statistics") or {}
    return TeamLine(
        provider_team_id=str(_require(raw, "teamId", ctx)),
        tricode=raw.get("teamTricode", ""),
        is_home=is_home,
        points=_stat(stats, "points"),
        fgm=_stat(stats, "fieldGoalsMade"),
        fga=_stat(stats, "fieldGoalsAttempted"),
        fg3m=_stat(stats, "threePointersMade"),
        fg3a=_stat(stats, "threePointersAttempted"),
        ftm=_stat(stats, "freeThrowsMade"),
        fta=_stat(stats, "freeThrowsAttempted"),
        oreb=_stat(stats, "reboundsOffensive"),
        dreb=_stat(stats, "reboundsDefensive"),
        assists=_stat(stats, "assists"),
        steals=_stat(stats, "steals"),
        blocks=_stat(stats, "blocks"),
        turnovers=_stat(stats, "turnovers"),
        fouls=_stat(stats, "foulsPersonal"),
        # The fields that make this table non-derivable from player rows.
        team_rebounds=stats.get("reboundsTeam"),
        team_turnovers=stats.get("turnoversTeam"),
    )


def parse_boxscore(payload: dict) -> BoxScore:
    """Parse a boxscore payload into provider-neutral lines."""
    game = _require(payload, "game", "boxscore payload")
    ctx = f"boxscore {game.get('gameId', '?')}"

    teams: list[TeamLine] = []
    players: list[PlayerLine] = []

    for key, is_home in (("homeTeam", True), ("awayTeam", False)):
        raw_team = _require(game, key, ctx)
        teams.append(_parse_team(raw_team, is_home=is_home))
        provider_team_id = str(raw_team["teamId"])
        for raw_player in raw_team.get("players") or []:
            players.append(_parse_player(raw_player, provider_team_id))

    return BoxScore(
        provider_game_id=str(_require(game, "gameId", ctx)),
        status=int(game.get("gameStatus", 0)),
        period=int(game.get("period", 0)),
        teams=teams,
        players=players,
    )


def fetch_boxscore(provider_game_id: str) -> BoxScore:
    """
    Fetch one game's box score.

    Raises ProviderError if the file isn't published — which is the normal state
    for a game that hasn't tipped off yet. Callers should treat that as "skip",
    not "crash".
    """
    return parse_boxscore(_get_json(BOXSCORE_URL.format(game_id=provider_game_id)))
