from app.database.session import SessionLocal
from app.database.models import Team
from nba_api.stats.static import teams


TEAM_METADATA = {
    "ATL": {"conference": "East", "division": "Southeast"},
    "BOS": {"conference": "East", "division": "Atlantic"},
    "BKN": {"conference": "East", "division": "Atlantic"},
    "CHA": {"conference": "East", "division": "Southeast"},
    "CHI": {"conference": "East", "division": "Central"},
    "CLE": {"conference": "East", "division": "Central"},
    "DAL": {"conference": "West", "division": "Southwest"},
    "DEN": {"conference": "West", "division": "Northwest"},
    "DET": {"conference": "East", "division": "Central"},
    "GSW": {"conference": "West", "division": "Pacific"},
    "HOU": {"conference": "West", "division": "Southwest"},
    "IND": {"conference": "East", "division": "Central"},
    "LAC": {"conference": "West", "division": "Pacific"},
    "LAL": {"conference": "West", "division": "Pacific"},
    "MEM": {"conference": "West", "division": "Southwest"},
    "MIA": {"conference": "East", "division": "Southeast"},
    "MIL": {"conference": "East", "division": "Central"},
    "MIN": {"conference": "West", "division": "Northwest"},
    "NOP": {"conference": "West", "division": "Southwest"},
    "NYK": {"conference": "East", "division": "Atlantic"},
    "OKC": {"conference": "West", "division": "Northwest"},
    "ORL": {"conference": "East", "division": "Southeast"},
    "PHI": {"conference": "East", "division": "Atlantic"},
    "PHX": {"conference": "West", "division": "Pacific"},
    "POR": {"conference": "West", "division": "Northwest"},
    "SAC": {"conference": "West", "division": "Pacific"},
    "SAS": {"conference": "West", "division": "Southwest"},
    "TOR": {"conference": "East", "division": "Atlantic"},
    "UTA": {"conference": "West", "division": "Northwest"},
    "WAS": {"conference": "East", "division": "Southeast"},
}


def fetch_and_store_teams():
    db = SessionLocal()
    try:
        nba_teams = teams.get_teams()

        for team in nba_teams:
            existing = db.query(Team).filter(
                Team.nba_api_id == team["id"]
            ).first()

            if not existing:
                abbr = team["abbreviation"]
                metadata = TEAM_METADATA.get(abbr, {})

                new_team = Team(
                    nba_api_id=team["id"],
                    name=team["nickname"],
                    city=team["city"],
                    abbreviation=abbr,
                    conference=metadata.get("conference", "Unknown"),
                    division=metadata.get("division", "Unknown"),
                )
                db.add(new_team)

        db.commit()
        print(f"Team sync complete. {len(nba_teams)} teams processed.")
    finally:
        db.close()


if __name__ == "__main__":
    fetch_and_store_teams()