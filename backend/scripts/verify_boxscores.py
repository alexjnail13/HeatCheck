"""
Check seeded box scores against invariants that must hold for real NBA data.

Row counts prove the pipeline ran. They don't prove it stored the right numbers
in the right columns — a swapped pair of fields produces exactly 30 rows too.
These checks test relationships that only hold if the mapping is correct:

  1. Player points sum to the team total. Every point is scored by a player, so
     this is an equality, not an approximation. Catches column misalignment.
  2. Exactly 5 starters per team. Catches a broken `started` derivation.
  3. Minutes sum to 240 per team in regulation (48 min x 5 players on court),
     +25 per overtime. Catches a minutes-parsing error.
  4. Team FGM equals the sum of player FGM. Field goals are fully attributed to
     players, unlike rebounds.
  5. team_game_stats.points agrees with games.home/away_team_score — which came
     from a DIFFERENT endpoint (LeagueGameFinder) during an earlier pipeline.
     Two independent sources agreeing is the strongest check here.

    python -m scripts.verify_boxscores            # every seeded game
    python -m scripts.verify_boxscores --limit 20

Exit 0 = all checks pass. Exit 1 = at least one violation, itemised.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from sqlalchemy import func

from app.database.models import (
    Game,
    Player,
    PlayerGameStats,
    Team,
    TeamGameStats,
)
from app.database.session import SessionLocal

REGULATION_SECONDS = 48 * 60 * 5  # 14400 — five players on court for 48 minutes
OVERTIME_SECONDS = 5 * 60 * 5  # 1500 per OT period
# Stat-correction games occasionally leave a few seconds unaccounted.
MINUTES_TOLERANCE = 300


def check_game(db, game: Game) -> list[str]:
    problems: list[str] = []
    tag = f"game {game.nba_game_id}"

    team_rows = db.query(TeamGameStats).filter(TeamGameStats.game_id == game.id).all()
    player_rows = (
        db.query(PlayerGameStats).filter(PlayerGameStats.game_id == game.id).all()
    )

    if len(team_rows) != 2:
        problems.append(f"{tag}: expected 2 team rows, found {len(team_rows)}")
        return problems
    if not player_rows:
        problems.append(f"{tag}: no player rows")
        return problems

    by_team: dict[int, list[PlayerGameStats]] = defaultdict(list)
    for row in player_rows:
        by_team[row.team_id].append(row)

    # 5. Cross-source agreement with the games table.
    for team_row in team_rows:
        expected = (
            game.home_team_score if team_row.is_home else game.away_team_score
        )
        if expected is not None and team_row.points != expected:
            problems.append(
                f"{tag}: team {team_row.team_id} box score says {team_row.points} pts, "
                f"games table says {expected}"
            )

    home_flags = sorted(t.is_home for t in team_rows)
    if home_flags != [False, True]:
        problems.append(f"{tag}: expected one home and one away team row")

    for team_row in team_rows:
        players = by_team.get(team_row.team_id, [])
        label = f"{tag} team {team_row.team_id}"

        if not players:
            problems.append(f"{label}: team row with no players")
            continue

        # 1. Points are fully attributed to players.
        player_points = sum(p.points for p in players)
        if player_points != team_row.points:
            problems.append(
                f"{label}: player points sum to {player_points}, "
                f"team total is {team_row.points}"
            )

        # 4. So are field goals.
        player_fgm = sum(p.fgm for p in players)
        if player_fgm != team_row.fgm:
            problems.append(
                f"{label}: player FGM sums to {player_fgm}, team FGM is {team_row.fgm}"
            )

        # 2. Exactly five starters.
        starters = sum(1 for p in players if p.started)
        if starters != 5:
            problems.append(f"{label}: {starters} starters, expected 5")

        # 3. Minutes reconcile with the length of the game.
        total_seconds = sum(p.seconds_played or 0 for p in players)
        overtimes = 0
        while (
            total_seconds
            > REGULATION_SECONDS + overtimes * OVERTIME_SECONDS + MINUTES_TOLERANCE
        ):
            overtimes += 1
            if overtimes > 6:
                break
        expected_seconds = REGULATION_SECONDS + overtimes * OVERTIME_SECONDS
        if abs(total_seconds - expected_seconds) > MINUTES_TOLERANCE:
            problems.append(
                f"{label}: minutes sum to {total_seconds}s "
                f"({total_seconds / 60:.1f} min), expected ~{expected_seconds}s "
                f"({overtimes} OT assumed)"
            )

        # A whole team of zeros means the columns didn't map.
        if all(p.points == 0 for p in players):
            problems.append(f"{label}: every player has 0 points")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="check at most N games")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seeded_ids = [
            gid for (gid,) in db.query(PlayerGameStats.game_id).distinct().all()
        ]
        if not seeded_ids:
            print("No seeded games found. Run app.pipeline.seed_boxscores first.")
            return 1

        query = db.query(Game).filter(Game.id.in_(seeded_ids)).order_by(Game.game_date)
        games = query.all()
        if args.limit:
            games = games[: args.limit]

        print(f"Checking {len(games)} seeded game(s)\n")

        all_problems: list[str] = []
        for game in games:
            problems = check_game(db, game)
            all_problems += problems
            status = "FAIL" if problems else "ok"
            print(f"  [{status}] {game.nba_game_id} {game.game_date}")
            for p in problems:
                print(f"         {p}")

        # Corpus-level summary.
        print("\nTOTALS")
        print(f"  players:           {db.query(Player).count()}")
        print(f"  player_game_stats: {db.query(PlayerGameStats).count()}")
        print(f"  team_game_stats:   {db.query(TeamGameStats).count()}")
        print(f"  team_external_ids: {db.query(Team).count()} teams mapped")

        top = (
            db.query(Player.full_name, PlayerGameStats.points, PlayerGameStats.seconds_played)
            .join(Player, Player.id == PlayerGameStats.player_id)
            .order_by(PlayerGameStats.points.desc())
            .limit(3)
            .all()
        )
        print("\n  highest-scoring lines seeded:")
        for name, points, seconds in top:
            mins = f"{(seconds or 0) // 60}:{(seconds or 0) % 60:02d}"
            print(f"    {name}: {points} pts in {mins}")

        # Two teams score ~220 points across ~30 player rows (including DNPs and
        # deep bench), so the all-rows mean lands near 7. Filtering to players who
        # actually took the floor gives the ~10-12 you'd recognise from a box score.
        avg_all = db.query(func.avg(PlayerGameStats.points)).scalar() or 0
        avg_played = (
            db.query(func.avg(PlayerGameStats.points))
            .filter(PlayerGameStats.seconds_played.isnot(None))
            .filter(PlayerGameStats.seconds_played > 0)
            .scalar()
            or 0
        )
        print(f"\n  mean points, all rows:      {float(avg_all):.1f} (expect ~6-8)")
        print(f"  mean points, players used:  {float(avg_played):.1f} (expect ~9-13)")

        print("\n" + "=" * 60)
        if all_problems:
            print(f"RESULT: {len(all_problems)} problem(s) found.")
            return 1
        print("RESULT: OK — all invariants hold.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
