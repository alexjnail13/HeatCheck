"""
Live ingestion — poll cdn.nba.com once, write to Postgres, exit.

This is the job that fixes the broken live feed. The old design polled
nba_api's scoreboard from inside the web service, computed win probability
inline, and broadcast it to WebSocket clients without storing anything. Three
things were wrong with that:

  1. It called a third-party API on the request hot path (principle #1).
  2. It stored nothing, so a user opening a live game at halftime had no first
     half to draw, and a finished game left no box score behind.
  3. It lived in the web service, so it died on free-tier spin-down and
     duplicated itself once Render ran more than one instance.

This script does the opposite: one pass, no loop, no server. Run it from a
Render Cron Job every minute during game hours; the web service only ever
reads what this wrote.

    python -m app.pipeline.ingest_live
    python -m app.pipeline.ingest_live --once --verbose

What it writes per poll:
  * games            — status, scores, and tipoff_utc backfilled from the feed
  * game_state_snapshots — an append-only row per distinct moment (live games)
  * player/team_game_stats — upserted cumulative totals (live and just-final)

It deliberately does NOT compute or store win probability. Snapshots hold raw
game state; the API runs the model fresh at read time, so retraining never
strands old rows (principle #3).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Game, GameStateSnapshot
from app.database.session import SessionLocal, describe_database
from app.providers import nba_cdn
from app.providers.nba_cdn import PROVIDER, GameSummary, ProviderError
from app.services.boxscore_store import (
    UnknownGameError,
    UnknownTeamError,
    resolve_game_id,
    store_boxscore,
)

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logger = logging.getLogger(__name__)

# Map the feed's numeric status onto the strings already in our games.status
# column, so the rest of the app doesn't learn a second vocabulary.
STATUS_TEXT = {
    nba_cdn.STATUS_SCHEDULED: "Scheduled",
    nba_cdn.STATUS_LIVE: "Live",
    nba_cdn.STATUS_FINAL: "Final",
}


def update_game_row(db: Session, game: Game, summary: GameSummary) -> bool:
    """
    Sync scores/status/tipoff onto the games row. Returns True if anything moved.

    Backfills tipoff_utc opportunistically: historical rows seeded from
    nba_api never had it, and the live feed hands it to us for free.
    """
    changed = False

    status = STATUS_TEXT.get(summary.status)
    if status and game.status != status:
        game.status = status
        changed = True

    if summary.home_score and game.home_team_score != summary.home_score:
        game.home_team_score = summary.home_score
        changed = True
    if summary.away_score and game.away_team_score != summary.away_score:
        game.away_team_score = summary.away_score
        changed = True

    if summary.tipoff_utc and game.tipoff_utc is None:
        game.tipoff_utc = summary.tipoff_utc
        changed = True

    return changed


def record_snapshot(db: Session, game_id: int, summary: GameSummary) -> bool:
    """
    Append a game-state snapshot. Returns True if a new row was written.

    Snapshots are an event time series, so they are INSERT-only — unlike box
    scores, which are cumulative totals and get upserted. The
    UNIQUE(game_id, period, clock) constraint absorbs an overlapping or retried
    cron run: the same moment simply fails to insert a second time.
    """
    snapshot = GameStateSnapshot(
        game_id=game_id,
        period=summary.period,
        clock=summary.game_clock,
        score_home=summary.home_score,
        score_away=summary.away_score,
    )
    db.add(snapshot)
    try:
        db.flush()
        return True
    except IntegrityError:
        # Same period+clock already recorded — the clock hasn't moved since the
        # last poll. Expected during timeouts and between possessions.
        db.rollback()
        return False


def ingest_game(db: Session, summary: GameSummary, *, verbose: bool = False) -> dict:
    """Process one game from the scoreboard. Caller owns the commit."""
    result = {"game": summary.provider_game_id, "snapshot": False, "boxscore": None}

    game_id = resolve_game_id(db, PROVIDER, summary.provider_game_id)
    game = db.get(Game, game_id)

    if update_game_row(db, game, summary):
        result["game_updated"] = True

    # Scheduled games have no state worth snapshotting and no box score file.
    if summary.status == nba_cdn.STATUS_SCHEDULED:
        return result

    if summary.is_live:
        result["snapshot"] = record_snapshot(db, game_id, summary)

    # Box score for live and just-finished games. A missing file is normal
    # rather than exceptional, so it degrades to a skip.
    try:
        box = nba_cdn.fetch_boxscore(summary.provider_game_id)
    except ProviderError as exc:
        if verbose:
            logger.info("  no box score for %s: %s", summary.provider_game_id, exc)
        return result

    if box.players:
        counts = store_boxscore(db, game_id, PROVIDER, box.teams, box.players)
        result["boxscore"] = counts

    return result


def run_once(*, verbose: bool = False) -> int:
    """One full pass over today's scoreboard. Returns a process exit code."""
    logger.info("Target database: %s", describe_database())
    try:
        games = nba_cdn.fetch_scoreboard()
    except ProviderError as exc:
        # A dead feed must not take the job down noisily every minute — log and
        # exit non-zero so Render surfaces it, but don't raise.
        logger.error("scoreboard unavailable: %s", exc)
        return 1

    if not games:
        logger.info("No games on the scoreboard (offseason or rest day).")
        return 0

    live = [g for g in games if g.is_live]
    logger.info(
        "%d game(s) on the board, %d live, at %s",
        len(games), len(live), datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    db = SessionLocal()
    processed = failed = snapshots = 0
    try:
        for summary in games:
            try:
                result = ingest_game(db, summary, verbose=verbose)
                # Commit per game so one bad game can't roll back the others.
                db.commit()
                processed += 1
                if result["snapshot"]:
                    snapshots += 1
                if verbose:
                    logger.info(
                        "  %s %s %s %d-%d%s",
                        summary.provider_game_id,
                        f"{summary.away_tricode}@{summary.home_tricode}",
                        summary.status_text,
                        summary.away_score,
                        summary.home_score,
                        " [snapshot]" if result["snapshot"] else "",
                    )
            except (UnknownGameError, UnknownTeamError) as exc:
                db.rollback()
                failed += 1
                logger.warning("  skipped %s: %s", summary.provider_game_id, exc)
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.error(
                    "  %s: %s: %s",
                    summary.provider_game_id, type(exc).__name__, exc,
                )
    finally:
        db.close()

    logger.info(
        "Done. %d processed, %d snapshots written, %d failed.",
        processed, snapshots, failed,
    )
    return 1 if failed and not processed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose", action="store_true", help="log every game, not just totals"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="accepted for clarity; this job always runs exactly one pass",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format=LOG_FORMAT
    )
    return run_once(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
