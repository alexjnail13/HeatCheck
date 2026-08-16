"""Baseline: the pre-Phase-A schema (teams, games, users, play_by_play).

Revision ID: 0000_baseline
Revises:
Create Date: 2026-08-11

Why this exists, written after it was needed:

These four tables predate Alembic — they were created by
Base.metadata.create_all() during Weeks 1-9 and had been live on Render for
months. When Alembic was adopted, 0001_phase_a was written to run against that
existing database, so it began with `ALTER TABLE games ADD COLUMN tipoff_utc`
and assumed the four tables were already there.

That worked exactly once, on the database that happened to have them. Pointed at
a brand-new Postgres it failed on its first statement, because the migration
history did not describe the whole schema — which is the entire point of having
one. A migration chain has to be able to build the database from nothing.

So this revision creates the pre-Phase-A tables, and 0001_phase_a now depends on
it. `alembic upgrade head` on an empty database produces the full schema.

FOR AN EXISTING PRE-ALEMBIC DATABASE (one that already has these four tables and
no alembic_version), do NOT run this — it would fail on tables that exist.
Instead mark it as already at this point, then migrate forward:

    alembic stamp 0000_baseline
    alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa

revision = "0000_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nba_team_id", sa.Integer(), nullable=False),
        sa.Column("abbreviation", sa.String(length=3), nullable=False),
        sa.Column("full_name", sa.String(length=50), nullable=False),
        sa.Column("city", sa.String(length=30), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("conference", sa.String(length=4), nullable=False),
        sa.Column("division", sa.String(length=15), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nba_team_id"),
        sa.UniqueConstraint("abbreviation"),
    )
    op.create_index("ix_teams_id", "teams", ["id"])

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nba_game_id", sa.String(length=10), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("home_team_score", sa.Integer(), nullable=True),
        sa.Column("away_team_score", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="scheduled"),
        sa.Column("season_type", sa.String(length=20), nullable=False,
                  server_default="Regular Season"),
        # NOTE: tipoff_utc is deliberately absent — 0001_phase_a adds it, and
        # replaying history in order has to reproduce the original shape.
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nba_game_id"),
    )
    op.create_index("ix_games_id", "games", ["id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "play_by_play",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("event_num", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("clock", sa.String(length=16), nullable=True),
        sa.Column("score_home", sa.Integer(), nullable=False),
        sa.Column("score_away", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_play_by_play_id", "play_by_play", ["id"])
    op.create_index("ix_play_by_play_game_id", "play_by_play", ["game_id"])


def downgrade() -> None:
    op.drop_table("play_by_play")
    op.drop_table("users")
    op.drop_table("games")
    op.drop_table("teams")
