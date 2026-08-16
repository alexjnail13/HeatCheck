"""
Print a stored box score for eyeballing against an external source.

verify_boxscores checks relationships INSIDE our data — player points summing
to the team total, minutes reconciling, and so on. Those catch column
misalignment, but they cannot catch an error that is internally consistent.
The only way to check that is to compare a game against a source outside the
system (Basketball Reference, NBA.com) and read it with your own eyes.

    python -m scripts.inspect_game --top 15        # biggest scoring lines, with game ids
    python -m scripts.inspect_game 0022400123      # full box score for one game
"""

from __future__ import annotations

import argparse
import sys

from app.database.models import (
    Game,
    Player,
    PlayerGameStats,
    Team,
    TeamGameStats,
)
from app.database.session import SessionLocal, describe_database


def show_top(db, limit: int) -> int:
    """Highest-scoring player-games, WITH the game id so they can be checked."""
    rows = (
        db.query(
            Player.full_name,
            PlayerGameStats.points,
            PlayerGameStats.seconds_played,
            PlayerGameStats.fgm,
            PlayerGameStats.fga,
            PlayerGameStats.fg3m,
            PlayerGameStats.ftm,
            Game.nba_game_id,
            Game.game_date,
            Game.season,
        )
        .join(Player, Player.id == PlayerGameStats.player_id)
        .join(Game, Game.id == PlayerGameStats.game_id)
        .order_by(PlayerGameStats.points.desc())
        .limit(limit)
        .all()
    )

    print(f"\nTop {limit} scoring lines\n")
    print(f"  {'PLAYER':<26} {'PTS':>4} {'MIN':>6} {'FG':>7} {'3P':>4} {'FT':>4}  "
          f"{'GAME':<12} {'DATE':<11} SEASON")
    print("  " + "-" * 88)
    for (name, pts, secs, fgm, fga, fg3m, ftm, gid, gdate, season) in rows:
        mins = f"{(secs or 0)//60}:{(secs or 0)%60:02d}"
        # A scoring line has to be reachable from the shot counts. If it isn't,
        # the points column disagrees with the shooting columns.
        implied = 2 * fgm + fg3m + ftm
        flag = "" if implied == pts else f"  <-- shots imply {implied}"
        print(f"  {name:<26} {pts:>4} {mins:>6} {fgm:>3}/{fga:<3} {fg3m:>4} {ftm:>4}  "
              f"{gid:<12} {gdate}  {season}{flag}")
    return 0


def show_game(db, nba_game_id: str) -> int:
    game = db.query(Game).filter(Game.nba_game_id == nba_game_id).first()
    if not game:
        print(f"No game with nba_game_id={nba_game_id!r}")
        return 1

    teams = {t.id: t for t in db.query(Team).all()}
    home = teams.get(game.home_team_id)
    away = teams.get(game.away_team_id)

    print(f"\n{away.abbreviation} @ {home.abbreviation}   {game.game_date}   "
          f"{game.season} {game.season_type}")
    print(f"games table score: {away.abbreviation} {game.away_team_score} - "
          f"{home.abbreviation} {game.home_team_score}   status={game.status}\n")

    for team_stat in (
        db.query(TeamGameStats).filter(TeamGameStats.game_id == game.id).all()
    ):
        team = teams.get(team_stat.team_id)
        label = "HOME" if team_stat.is_home else "AWAY"
        print(f"--- {team.abbreviation} ({label}) --- {team_stat.points} pts, "
              f"{team_stat.fgm}/{team_stat.fga} FG, {team_stat.fg3m}/{team_stat.fg3a} 3P")
        print(f"  {'PLAYER':<26} {'S':<2} {'MIN':>6} {'PTS':>4} {'FG':>7} {'3P':>6} "
              f"{'FT':>6} {'REB':>4} {'AST':>4} {'+/-':>5}")

        rows = (
            db.query(PlayerGameStats, Player)
            .join(Player, Player.id == PlayerGameStats.player_id)
            .filter(
                PlayerGameStats.game_id == game.id,
                PlayerGameStats.team_id == team_stat.team_id,
            )
            .all()
        )
        rows.sort(key=lambda r: (not r[0].started, -(r[0].seconds_played or 0)))

        total = 0
        for stat, player in rows:
            if stat.seconds_played is None:
                print(f"  {player.full_name:<26} {'':<2} {'DNP':>6}")
                continue
            total += stat.points
            mins = f"{stat.seconds_played//60}:{stat.seconds_played%60:02d}"
            pm = "--" if stat.plus_minus is None else f"{stat.plus_minus:+d}"
            print(f"  {player.full_name:<26} {'*' if stat.started else '':<2} "
                  f"{mins:>6} {stat.points:>4} {stat.fgm:>3}/{stat.fga:<3} "
                  f"{stat.fg3m:>2}/{stat.fg3a:<3} {stat.ftm:>2}/{stat.fta:<3} "
                  f"{stat.oreb + stat.dreb:>4} {stat.assists:>4} {pm:>5}")

        print(f"  {'players sum':<26} {'':<2} {'':>6} {total:>4}   "
              f"(team row says {team_stat.points})\n")

    print("Compare against basketball-reference.com or nba.com for this date.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_id", nargs="?", help="nba_game_id, e.g. 0022400123")
    parser.add_argument("--top", type=int, help="show the N highest-scoring lines")
    args = parser.parse_args()

    print(f"Target database: {describe_database()}")

    db = SessionLocal()
    try:
        if args.top:
            return show_top(db, args.top)
        if args.game_id:
            return show_game(db, args.game_id)
        parser.print_help()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
