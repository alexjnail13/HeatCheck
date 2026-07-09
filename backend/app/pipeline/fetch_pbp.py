"""
Fetch play-by-play data from nba_api and build training dataset for win probability model.

For each completed game in our database:
1. Fetch play-by-play events from PlayByPlayV3
2. Extract features: point_differential, time_remaining_seconds, team_strength_diff
3. Attach label: 1 if home team won, 0 if not
4. Save incrementally to CSV for crash recovery
"""

import time
import logging
import os

import pandas as pd
from nba_api.stats.endpoints import playbyplayv3

from app.database.session import SessionLocal
from app.database.models import Game
from app.ml.features import calc_time_remaining, get_team_win_pcts, extract_event_features

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "training_data.csv")
REQUEST_DELAY = 1.5          # seconds between API calls 
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: process ONE game's play‑by‑play into feature rows
# ---------------------------------------------------------------------------
def process_game_pbp(pbp_df: pd.DataFrame, game: Game,
                     home_wp: float, away_wp: float) -> list[dict]:
    """
    Takes the raw play-by-play DataFrame for a single game and
    extracts one training row per scoring event.

    Uses the shared `extract_event_features` so the features here match
    exactly what the inference endpoint computes (no train/serve skew).

    Features per row:
        - point_differential  (home - away)
        - time_remaining_seconds
        - team_strength_diff  (home win% - away win%)
        - home_team_won       (label: 1 or 0)
    """
    rows: list[dict] = []
    label = 1 if game.home_team_score > game.away_team_score else 0

    for _, event in pbp_df.iterrows():
        feats = extract_event_features(event)
        if feats is None:
            continue

        rows.append({
            "nba_game_id": game.nba_game_id,
            "period": feats["period"],
            "time_remaining_seconds": feats["time_remaining_seconds"],
            "point_differential": feats["point_differential"],
            "team_strength_diff": round(home_wp - away_wp, 4),
            "home_team_won": label,
        })

    return rows


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    # --- Step 1: Load existing progress (crash recovery) -----------------
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)

    processed_game_ids: set[str] = set()
    if os.path.exists(CSV_PATH):
        existing_df = pd.read_csv(CSV_PATH)
        processed_game_ids = set(existing_df["nba_game_id"].unique())
        logger.info(f"Found existing CSV with {len(processed_game_ids)} games already processed.")
    else:
        logger.info("No existing CSV found — starting fresh.")

    # --- Step 2: Query database for completed games ----------------------
    db = SessionLocal()
    try:
        games = db.query(Game).filter(Game.status == "Final").all()
        logger.info(f"Found {len(games)} completed games in database.")

        # Pre-compute team win percentages
        win_pcts = get_team_win_pcts(db)
        logger.info(f"Computed win percentages for {len(win_pcts)} teams.")
    finally:
        db.close()

    # --- Step 3: Fetch play-by-play for each game ------------------------
    games_to_process = [g for g in games if g.nba_game_id not in processed_game_ids]
    logger.info(f"{len(games_to_process)} games remaining to process.")

    for i, game in enumerate(games_to_process):
        logger.info(
            f"[{i + 1}/{len(games_to_process)}] Fetching PBP for game {game.nba_game_id}"
        )

        try:
            # Fetch from nba_api — PlayByPlayV3
            pbp = playbyplayv3.PlayByPlayV3(
                game_id=game.nba_game_id,
                start_period=0,
                end_period=14,  # covers all periods including OT
            )
            pbp_df = pbp.get_data_frames()[0]

            if pbp_df.empty:
                logger.warning(f"No PBP data for game {game.nba_game_id}, skipping.")
                time.sleep(REQUEST_DELAY)
                continue

            # Get team win percentages (default to 0.5 if missing)
            home_wp = win_pcts.get(game.home_team_id, 0.5)
            away_wp = win_pcts.get(game.away_team_id, 0.5)

            # Extract feature rows
            new_rows = process_game_pbp(pbp_df, game, home_wp, away_wp)

            if new_rows:
                new_df = pd.DataFrame(new_rows)
                # Append to CSV — write header only if file doesn't exist yet
                header = not os.path.exists(CSV_PATH)
                new_df.to_csv(CSV_PATH, mode="a", header=header, index=False)
                logger.info(f"  → Saved {len(new_rows)} rows for game {game.nba_game_id}")
            else:
                logger.warning(f"  → No valid rows extracted for {game.nba_game_id}")

        except Exception as e:
            logger.error(f"Error processing game {game.nba_game_id}: {e}")

        # Rate limiting — don't hammer the API
        time.sleep(REQUEST_DELAY)

    logger.info("Pipeline complete!")


if __name__ == "__main__":
    main()