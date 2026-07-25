from sqlalchemy import Column, Integer, String, Date, ForeignKey, Float, DateTime
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