"""
Seed the play_by_play table from nba_api.

For each completed game in our database, fetch PlayByPlayV3 and store its
scoring events so the win-probability endpoint can read play-by-play from our
own Postgres instead of calling stats.nba.com live (which Render's datacenter
IP is blocked from).

We store the RAW fields the feature function consumes (period, clock, scores)
plus an ordering key (event_num) — not computed features — so the model stays
decoupled from the stored data.

Run from your laptop (nba_api is reachable there, not from Render):
    $env:DATABASE_URL="<External Database URL>"
    python -m app.pipeline.seed_pbp

Idempotent: games already present in play_by_play are skipped, so it's safe to
re-run after an interruption.
"""

import time
import logging

from nba_api.stats.endpoints import playbyplayv3

from app.database.session import SessionLocal, describe_database
from app.database.models import Game, PlayByPlay

REQUEST_DELAY = 1.5  # seconds between API calls — don't hammer nba_api
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


def store_game_pbp(db, game: Game) -> int:
    """Fetch and store one game's play-by-play. Returns number of events stored."""
    pbp = playbyplayv3.PlayByPlayV3(
        game_id=game.nba_game_id,
        start_period=0,
        end_period=14,  # covers regulation + overtime
    )
    df = pbp.get_data_frames()[0]
    if df.empty:
        return 0

    events: list[PlayByPlay] = []
    for _, row in df.iterrows():
        score_home = row.get("scoreHome")
        score_away = row.get("scoreAway")
        period = row.get("period")

        # Skip events with no usable score/period — same rule the feature
        # function uses, so we only store events the curve actually needs.
        if score_home is None or score_away is None or period is None:
            continue
        try:
            score_home = int(score_home)
            score_away = int(score_away)
        except (ValueError, TypeError):
            continue

        events.append(
            PlayByPlay(
                game_id=game.id,
                event_num=int(row.get("actionNumber", 0)),
                period=int(period),
                clock=row.get("clock") or None,
                score_home=score_home,
                score_away=score_away,
            )
        )

    if events:
        db.bulk_save_objects(events)
        db.commit()
    return len(events)


def main() -> None:
    # This used to call Base.metadata.create_all(). It doesn't anymore.
    #
    # create_all() silently creates tables OUTSIDE Alembic, leaving no
    # alembic_version row — so the database looks migrated but isn't tracked,
    # and the next `alembic upgrade head` tries to create tables that already
    # exist. Schema is owned by Alembic and only by Alembic:
    #
    #     alembic upgrade head
    #
    # If the tables are missing, that's the fix — not a silent create here.
    print(f"Target database: {describe_database()}\n")

    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.status == "Final").all()

        # Crash recovery: skip games already seeded (commit is per-game, so each
        # game is all-or-nothing).
        already = {gid for (gid,) in db.query(PlayByPlay.game_id).distinct().all()}
        todo = [g for g in games if g.id not in already]

        logger.info(
            f"{len(games)} final games, {len(already)} already seeded, "
            f"{len(todo)} to process."
        )

        for i, game in enumerate(todo):
            try:
                n = store_game_pbp(db, game)
                logger.info(f"[{i + 1}/{len(todo)}] {game.nba_game_id}: stored {n} events")
            except Exception as exc:
                db.rollback()
                logger.error(f"{game.nba_game_id}: {exc}")
            time.sleep(REQUEST_DELAY)

        logger.info("Play-by-play seeding complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
