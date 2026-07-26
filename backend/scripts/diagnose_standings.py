"""
Diagnostic: check whether the seeded regular-season data is complete.

A full NBA regular season is 1230 games, and every team plays exactly 82.
Any deviation means games are missing from the seed (not a standings math bug).

Run against production:
    $env:DATABASE_URL="<External Database URL>"
    python diagnose_standings.py
"""

from collections import defaultdict

from sqlalchemy import func

from app.database.session import SessionLocal
from app.database.models import Game, Team


def main() -> None:
    db = SessionLocal()

    season = db.query(func.max(Game.season)).scalar()
    print(f"Latest season in DB: {season}\n")

    # How the data breaks down by game-id prefix (001 pre, 002 reg, 004 playoff, 005 play-in)
    print("--- games by id prefix ---")
    prefix_counts: dict[str, int] = defaultdict(int)
    for (gid,) in db.query(Game.nba_game_id).filter(Game.season == season).all():
        prefix_counts[gid[:3]] += 1
    labels = {"001": "preseason", "002": "regular", "003": "all-star",
              "004": "playoffs", "005": "play-in"}
    for prefix in sorted(prefix_counts):
        print(f"  {prefix} ({labels.get(prefix, '?'):9}) : {prefix_counts[prefix]}")

    # Regular season completeness
    regular = (
        db.query(Game)
        .filter(
            Game.season == season,
            Game.status == "Final",
            Game.nba_game_id.like("002%"),
        )
        .all()
    )
    print(f"\nRegular-season Final games: {len(regular)}  (expected 1230)")

    # Games played per team
    played: dict[int, int] = defaultdict(int)
    missing_scores = 0
    for g in regular:
        if g.home_team_score is None or g.away_team_score is None:
            missing_scores += 1
            continue
        played[g.home_team_id] += 1
        played[g.away_team_id] += 1

    if missing_scores:
        print(f"⚠️  {missing_scores} regular-season games have a NULL score "
              f"(these are skipped by the standings computation)")

    print("\n--- teams not at 82 games ---")
    teams = db.query(Team).order_by(Team.full_name).all()
    off = 0
    for t in teams:
        n = played.get(t.id, 0)
        if n != 82:
            off += 1
            print(f"  {t.full_name:26} {n:3} games  ({n - 82:+d})")
    if off == 0:
        print("  ✅ all 30 teams have exactly 82 games")

    db.close()


if __name__ == "__main__":
    main()
