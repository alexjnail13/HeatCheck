from datetime import datetime
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.database.models import Game, Team
from nba_api.stats.endpoints import leaguegamefinder


def fetch_and_store_games(season: str = "2024-25"):
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

            if "@" in row["MATCHUP"]:
                # This team is the away team
                game_dict[game_id]["away_team_id"] = db_team_id
                game_dict[game_id]["away_team_score"] = row["PTS"]
            else:
                # This team is the home team
                game_dict[game_id]["home_team_id"] = db_team_id
                game_dict[game_id]["home_team_score"] = row["PTS"]

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
            f"Games sync complete. {len(game_dict)} games found, "
            f"{inserted} new games inserted, {skipped} skipped (untracked teams)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    fetch_and_store_games()