"""
Diagnostic: find which regular-season games are missing from the DB, and why.

Re-queries LeagueGameFinder (works from your laptop, not from Render), rebuilds
the same game_dict that fetch_games builds, and reports:
  1. games the API returned but our DB doesn't have
  2. for each, whether the home/away side failed to resolve, and the raw rows

Run:
    $env:DATABASE_URL="<External Database URL>"
    python diagnose_missing_games.py
"""

from collections import defaultdict

from sqlalchemy import func
from nba_api.stats.endpoints import leaguegamefinder

from app.database.session import SessionLocal
from app.database.models import Game, Team


def main() -> None:
    db = SessionLocal()
    season = db.query(func.max(Game.season)).scalar()
    print(f"Season: {season}\n")

    team_lookup = {t.nba_team_id: t for t in db.query(Team).all()}
    have = {gid for (gid,) in db.query(Game.nba_game_id).all()}

    rows = leaguegamefinder.LeagueGameFinder(
        season_nullable=season, league_id_nullable="00"
    ).get_normalized_dict()["LeagueGameFinderResults"]

    # Group raw rows by game id (regular season only)
    by_game: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["GAME_ID"].startswith("002"):
            by_game[r["GAME_ID"]].append(r)

    print(f"API regular-season games: {len(by_game)}")
    print(f"In our database:          {sum(1 for g in by_game if g in have)}\n")

    missing = [g for g in sorted(by_game) if g not in have]
    print(f"--- {len(missing)} missing regular-season games ---")

    for gid in missing:
        rs = by_game[gid]
        print(f"\nGAME_ID {gid}   ({len(rs)} row(s) returned by the API)")
        for r in rs:
            known = "known" if r["TEAM_ID"] in team_lookup else "UNKNOWN TEAM"
            side = "away" if "@" in r["MATCHUP"] else "home"
            print(
                f"   {r['TEAM_ABBREVIATION']:4} {r['MATCHUP']:14} "
                f"{r['GAME_DATE']}  side={side:4} pts={r['PTS']}  [{known}]"
            )
        sides = {"away" if "@" in r["MATCHUP"] else "home" for r in rs}
        if len(rs) < 2:
            print("   -> CAUSE: API returned only one row, so the other side is unset")
        elif len(sides) < 2:
            print(f"   -> CAUSE: both rows parsed as '{sides.pop()}' (MATCHUP format)")
        else:
            print("   -> CAUSE: both sides present — check team lookup / scores")

    db.close()


if __name__ == "__main__":
    main()
