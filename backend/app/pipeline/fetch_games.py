"""
Fetch a season's schedule and results into the games table.

    python -m app.pipeline.fetch_games                    # current default season
    python -m app.pipeline.fetch_games --season 2024-25
    python -m app.pipeline.fetch_games --season 2024-25 --season 2025-26

Run from your laptop: nba_api talks to stats.nba.com, which blocks datacenter IPs.
"""

import argparse
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.session import SessionLocal, describe_database
from app.database.models import Game, Team
from nba_api.stats.endpoints import leaguegamefinder

DEFAULT_SEASON = "2025-26"


def fetch_and_store_games(season: str = DEFAULT_SEASON):
    db = SessionLocal()
    try:
        # Fetch all games for the season
        gamefinder = leaguegamefinder.LeagueGameFinder(
            season_nullable=season,
            league_id_nullable="00"
        )
        rows = gamefinder.get_normalized_dict()["LeagueGameFinderResults"]

        # Build a lookup: nba_api team ID -> our database team ID
        teams = db.query(Team).all()
        team_lookup = {team.nba_team_id: team.id for team in teams}

        # Combine two rows per game into one record
        game_dict = {}

        for row in rows:
            game_id = row["GAME_ID"]

            if game_id not in game_dict:
                game_dict[game_id] = {
                    "nba_game_id": game_id,
                    "game_date": datetime.strptime(row["GAME_DATE"], "%Y-%m-%d").date(),
                    "season": season,
                    "season_type": "Playoffs" if game_id.startswith("004") else "Regular Season",
                }

            nba_team_id = row["TEAM_ID"]
            db_team_id = team_lookup.get(nba_team_id)

            # Determine home/away from the MATCHUP string itself rather than
            # assuming it's written from THIS row's perspective. Usually the API
            # flips it per team ("NYK @ ORL" / "ORL vs. NYK"), but for neutral-site
            # games (NBA Cup in Las Vegas, global games) BOTH rows carry the same
            # string — which made the old `"@" in MATCHUP` check mark both teams
            # away, leaving home_team_id unset and silently dropping the game.
            matchup = row["MATCHUP"]
            if " @ " in matchup:
                away_abbr, home_abbr = (s.strip() for s in matchup.split(" @ ", 1))
            elif " vs. " in matchup:
                home_abbr, away_abbr = (s.strip() for s in matchup.split(" vs. ", 1))
            else:
                continue  # unrecognised format — don't guess

            if row["TEAM_ABBREVIATION"] == home_abbr:
                game_dict[game_id]["home_team_id"] = db_team_id
                game_dict[game_id]["home_team_score"] = row["PTS"]
            else:
                game_dict[game_id]["away_team_id"] = db_team_id
                game_dict[game_id]["away_team_score"] = row["PTS"]

        # Insert games into database
        inserted = 0
        skipped = 0
        for game_data in game_dict.values():
            # Skip games whose teams we don't track — All-Star (game id "003..."),
            # exhibition, and international squads aren't in our teams table, so
            # their ids resolve to None and would violate the NOT NULL FK columns.
            if game_data.get("home_team_id") is None or game_data.get("away_team_id") is None:
                skipped += 1
                continue

            existing = db.query(Game).filter(
                Game.nba_game_id == game_data["nba_game_id"]
            ).first()

            if not existing:
                # Determine game status based on whether scores exist
                has_scores = game_data.get("home_team_score") is not None
                game_data["status"] = "Final" if has_scores else "Scheduled"

                new_game = Game(**game_data)
                db.add(new_game)
                inserted += 1

        db.commit()
        print(
            f"[{season}] sync complete. {len(game_dict)} games found, "
            f"{inserted} new games inserted, {skipped} skipped (untracked teams)."
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season",
        action="append",
        help='Season to fetch, e.g. "2024-25". Repeat for multiple seasons.',
    )
    args = parser.parse_args()

    print(f"Target database: {describe_database()}\n")

    for season in args.season or [DEFAULT_SEASON]:
        fetch_and_store_games(season)


if __name__ == "__main__":
    main()