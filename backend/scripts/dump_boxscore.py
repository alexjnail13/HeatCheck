"""
Capture a REAL box score payload and check it against what the parser expects.

Why this exists: the scoreboard parser was written against a real response, but
the boxscore parser was written against the documented NBA live-boxscore shape,
not a payload we actually retrieved. If a stat key is named differently than
assumed, the parser silently reads a default instead of crashing — the exact
class of bug that quietly zeroes a season of data.

Run this once a game is in progress or finished:

    python -m scripts.dump_boxscore                # auto-picks a game from today
    python -m scripts.dump_boxscore 0022400123     # or name one

It writes the raw JSON to boxscore_<id>.json and reports which fields the parser
expects but did not find.
"""

import json
import sys

from app.providers import nba_cdn
from app.providers.nba_cdn import ProviderError

# What _parse_player / _parse_team read out of "statistics".
EXPECTED_PLAYER_STATS = [
    "points", "fieldGoalsMade", "fieldGoalsAttempted",
    "threePointersMade", "threePointersAttempted",
    "freeThrowsMade", "freeThrowsAttempted",
    "reboundsOffensive", "reboundsDefensive",
    "assists", "steals", "blocks", "turnovers", "foulsPersonal",
    "minutes", "plusMinusPoints",
]
EXPECTED_TEAM_STATS = EXPECTED_PLAYER_STATS[:-2] + ["reboundsTeam", "turnoversTeam"]
EXPECTED_PLAYER_KEYS = ["personId", "name", "starter", "position", "jerseyNum"]


def pick_game_id() -> str | None:
    """Find a game from today that has actually tipped off."""
    games = nba_cdn.fetch_scoreboard()
    if not games:
        print("No games on today's scoreboard (offseason?). Pass a game id instead.")
        return None
    started = [g for g in games if g.status in (nba_cdn.STATUS_LIVE, nba_cdn.STATUS_FINAL)]
    if not started:
        print(f"{len(games)} game(s) today, none tipped off yet. Try again later.")
        return None
    chosen = started[0]
    print(f"Using {chosen.provider_game_id} "
          f"({chosen.away_tricode} @ {chosen.home_tricode}, {chosen.status_text})")
    return chosen.provider_game_id


def report_missing(label: str, present: set[str], expected: list[str]) -> list[str]:
    missing = [k for k in expected if k not in present]
    if missing:
        print(f"  !! {label}: parser expects but feed does NOT have: {missing}")
    else:
        print(f"  OK {label}: all {len(expected)} expected fields present")
    return missing


def main() -> int:
    game_id = sys.argv[1] if len(sys.argv) > 1 else pick_game_id()
    if not game_id:
        return 1

    url = nba_cdn.BOXSCORE_URL.format(game_id=game_id)
    try:
        payload = nba_cdn._get_json(url)
    except ProviderError as exc:
        print(f"FAILED: {exc}")
        return 1

    out = f"boxscore_{game_id}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nRaw payload written to {out}\n")

    game = payload.get("game", {})
    print(f"gameStatus={game.get('gameStatus')} period={game.get('period')}")

    problems: list[str] = []
    for side in ("homeTeam", "awayTeam"):
        team = game.get(side, {})
        print(f"\n{side} ({team.get('teamTricode')}):")

        problems += report_missing(
            "team statistics", set(team.get("statistics") or {}), EXPECTED_TEAM_STATS
        )

        players = team.get("players") or []
        print(f"  {len(players)} player rows")
        if players:
            p = players[0]
            problems += report_missing("player keys", set(p), EXPECTED_PLAYER_KEYS)
            problems += report_missing(
                "player statistics", set(p.get("statistics") or {}), EXPECTED_PLAYER_STATS
            )
            print(f"  sample: {p.get('name')} "
                  f"minutes={p.get('statistics', {}).get('minutes')!r} "
                  f"starter={p.get('starter')!r}")

    # Now run the real parser end to end.
    print("\n--- parsing with the real parser ---")
    try:
        box = nba_cdn.parse_boxscore(payload)
    except Exception as exc:
        print(f"PARSER FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"parsed {len(box.players)} players, {len(box.teams)} teams")
    played = [p for p in box.players if p.seconds_played]
    if played:
        top = max(played, key=lambda p: p.points)
        print(f"top scorer: {top.full_name} {top.points}pts "
              f"{top.fgm}/{top.fga}fg {top.oreb + top.dreb}reb "
              f"{top.seconds_played}s (={top.seconds_played // 60}:{top.seconds_played % 60:02d})")
    for t in box.teams:
        print(f"  {t.tricode} (home={t.is_home}): {t.points}pts "
              f"team_reb={t.team_rebounds} team_to={t.team_turnovers}")

    if problems:
        print(f"\nRESULT: {len(problems)} field-name mismatch(es) — parser needs updating.")
        return 1
    print("\nRESULT: OK — parser assumptions match the live feed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
