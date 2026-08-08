from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.database.session import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    nba_team_id = Column(Integer, unique=True, nullable=False)
    abbreviation = Column(String(3), unique=True, nullable=False)
    full_name = Column(String(50), nullable=False)
    city = Column(String(30), nullable=False)
    state = Column(String(30), nullable=False)
    conference = Column(String(4), nullable=False)
    division = Column(String(15), nullable=False)


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    nba_game_id = Column(String(10), unique=True, nullable=False)
    season = Column(String(7), nullable=False)
    game_date = Column(Date, nullable=False)
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    home_team_score = Column(Integer, nullable=True)
    away_team_score = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="scheduled")
    season_type = Column(String(20), nullable=False, default="Regular Season")
    # Exact tipoff in UTC. `game_date` is a local calendar date and is fine for
    # display, but it is NOT a safe join key across providers: a 10:30pm ET tip
    # on Jan 5 is Jan 6 in UTC, so matching a provider's game to ours by date
    # alone silently drops west-coast games. Nullable because historical rows
    # seeded from nba_api never had it.
    tipoff_utc = Column(DateTime(timezone=True), nullable=True, index=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlayByPlay(Base):
    __tablename__ = "play_by_play"

    id = Column(Integer, primary_key=True, index=True)
    # Which game this event belongs to. Indexed because the win-probability
    # endpoint always queries "all events for one game".
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    # Ordering key from PlayByPlayV3 — lets us ORDER BY to rebuild the game
    # chronologically (SQL rows have no inherent order).
    event_num = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    clock = Column(String(16), nullable=True)  # ISO clock e.g. "PT04M30.00S"
    score_home = Column(Integer, nullable=False)
    score_away = Column(Integer, nullable=False)


# ---------------------------------------------------------------------------
# Provider identity mapping
# ---------------------------------------------------------------------------
# One small table per entity instead of (a) provider-id columns on the entity
# tables or (b) a single generic (entity_type, entity_id, ...) table.
#
#   - vs. columns: adding a 4th provider is an INSERT, not an ALTER TABLE on a
#     live production database. Three migrations total, forever — not three per
#     provider, per entity.
#   - vs. one generic table: a generic `entity_id` would be a polymorphic
#     association pointing at three different tables depending on entity_type,
#     which Postgres cannot enforce with a foreign key. Splitting per entity
#     keeps real FKs and real uniqueness constraints.
#
# `provider` is a short slug: "nba_api", "msf", "balldontlie", "the_odds_api".


class TeamExternalId(Base):
    __tablename__ = "team_external_ids"
    __table_args__ = (
        # A provider's ID resolves to exactly one of our teams...
        UniqueConstraint("provider", "provider_id", name="uq_team_ext_provider_id"),
        # ...and one of our teams has exactly one ID per provider.
        UniqueConstraint("team_id", "provider", name="uq_team_ext_team_provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    provider_id = Column(String(40), nullable=False)
    # Provider's own abbreviation, which does NOT agree across feeds
    # (PHX vs PHO, BKN vs BRK). Teams.abbreviation stays OUR canonical value;
    # each provider's spelling is stored beside it here.
    provider_abbreviation = Column(String(8), nullable=True)


class GameExternalId(Base):
    __tablename__ = "game_external_ids"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_game_ext_provider_id"),
        UniqueConstraint("game_id", "provider", name="uq_game_ext_game_provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    provider_id = Column(String(40), nullable=False)


class PlayerExternalId(Base):
    __tablename__ = "player_external_ids"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_player_ext_provider_id"),
        UniqueConstraint("player_id", "provider", name="uq_player_ext_player_provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    provider_id = Column(String(40), nullable=False)


# ---------------------------------------------------------------------------
# Players and box scores
# ---------------------------------------------------------------------------


class Player(Base):
    """
    Player identity ONLY — no current team.

    A player traded mid-season has games for both teams; a `team_id` here would
    rewrite history every time we re-synced. The team a player played for in a
    given game lives on the stat row instead (see PlayerGameStats.team_id).
    """

    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(80), nullable=False, index=True)
    first_name = Column(String(40), nullable=True)
    last_name = Column(String(40), nullable=True)
    position = Column(String(8), nullable=True)
    jersey_number = Column(String(4), nullable=True)  # string: "00" != "0"


class PlayerGameStats(Base):
    """
    One row per player per game — raw counting stats only.

    Deliberately stores NO percentages. fg_pct is fgm/fga: derivable, so storing
    it can drift out of sync with the numbers it came from (principle #3), and
    it discards attempt volume, which is real signal for the Phase C prop models.
    """

    __tablename__ = "player_game_stats"
    __table_args__ = (
        # Re-running ingestion for a game must update, not duplicate.
        UniqueConstraint("game_id", "player_id", name="uq_pgs_game_player"),
    )

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    # Which team the player played for IN THIS GAME. Survives trades.
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)

    # Seconds, not minutes: "32:41" -> 1961. Minutes-only truncation is a
    # systematic error that compounds in per-minute rate features.
    # NULL = did not play (distinct from 0 seconds played).
    seconds_played = Column(Integer, nullable=True)
    started = Column(Boolean, nullable=False, default=False)

    points = Column(Integer, nullable=False, default=0)
    fgm = Column(Integer, nullable=False, default=0)
    fga = Column(Integer, nullable=False, default=0)
    fg3m = Column(Integer, nullable=False, default=0)
    fg3a = Column(Integer, nullable=False, default=0)
    ftm = Column(Integer, nullable=False, default=0)
    fta = Column(Integer, nullable=False, default=0)
    # Split, not a single `rebounds`: total is derivable from the split, but the
    # split is NOT recoverable from the total. Offensive rebounds track effort
    # and lineup role; defensive rebounds track opportunity.
    oreb = Column(Integer, nullable=False, default=0)
    dreb = Column(Integer, nullable=False, default=0)
    assists = Column(Integer, nullable=False, default=0)
    steals = Column(Integer, nullable=False, default=0)
    blocks = Column(Integer, nullable=False, default=0)
    turnovers = Column(Integer, nullable=False, default=0)
    fouls = Column(Integer, nullable=False, default=0)
    # Nullable: not every provider reports +/-, and 0 is a real value.
    plus_minus = Column(Integer, nullable=True)


class TeamGameStats(Base):
    """
    Team totals per game — stored, not derived by summing player rows.

    Not a performance decision (summing 10 rows is nothing). Team totals are
    genuinely NOT the sum of player rows: team rebounds, team turnovers and
    technical fouls belong to no player. The provider hands us these totals, so
    deriving them would manufacture facts we were already given (principle #2).
    """

    __tablename__ = "team_game_stats"
    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_tgs_game_team"),
    )

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    is_home = Column(Boolean, nullable=False)

    points = Column(Integer, nullable=False, default=0)
    fgm = Column(Integer, nullable=False, default=0)
    fga = Column(Integer, nullable=False, default=0)
    fg3m = Column(Integer, nullable=False, default=0)
    fg3a = Column(Integer, nullable=False, default=0)
    ftm = Column(Integer, nullable=False, default=0)
    fta = Column(Integer, nullable=False, default=0)
    oreb = Column(Integer, nullable=False, default=0)
    dreb = Column(Integer, nullable=False, default=0)
    assists = Column(Integer, nullable=False, default=0)
    steals = Column(Integer, nullable=False, default=0)
    blocks = Column(Integer, nullable=False, default=0)
    turnovers = Column(Integer, nullable=False, default=0)
    fouls = Column(Integer, nullable=False, default=0)
    # Team-level only — these are exactly the fields that make this table
    # non-derivable from player rows.
    team_rebounds = Column(Integer, nullable=True)
    team_turnovers = Column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Live game state
# ---------------------------------------------------------------------------


class GameStateSnapshot(Base):
    """
    Point-in-time score/clock for an IN-PROGRESS game, written by the ingestion
    job. Kept separate from play_by_play on purpose: once a game is final we
    backfill ~450 real play-by-play events for it, and interleaving those with
    ~90 poll snapshots would draw the win-probability curve from two sources.
    Separate tables means the read path picks one — snapshots while live,
    play_by_play once final.

    Stores raw game state only, never a predicted probability: the WP endpoint
    computes features and runs the model fresh at read time, so retraining
    doesn't strand old rows (principle #3).
    """

    __tablename__ = "game_state_snapshots"
    __table_args__ = (
        # Idempotency guard: a cron run that overlaps or retries must not
        # double-insert the same moment.
        UniqueConstraint("game_id", "period", "clock", name="uq_snapshot_moment"),
    )

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    # Ordering key. play_by_play has event_num, but a polled scoreboard gives a
    # snapshot with no event numbering — wall-clock capture time is what orders
    # these rows.
    captured_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    period = Column(Integer, nullable=False)
    clock = Column(String(16), nullable=True)
    score_home = Column(Integer, nullable=False)
    score_away = Column(Integer, nullable=False)