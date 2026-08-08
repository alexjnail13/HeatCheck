"""
Diagnostic: is cdn.nba.com reachable from wherever this runs?

The blocked-feed problem was always specific to stats.nba.com, which rejects
datacenter IPs. cdn.nba.com is a different host (an S3-backed CDN) and may not
share that behaviour — but the only way to know is to ask from the machine that
matters. Run this ON RENDER, not on your laptop: a laptop is a residential IP
and will succeed even in the case where production fails.

    python -m scripts.check_nba_cdn

Exit code 0 = every endpoint we need is reachable.
Exit code 1 = at least one failed; the output says which and why.
"""

import json
import sys
import time
from typing import Any

import requests

SCOREBOARD_URL = (
    "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
)
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
# The old, known-blocked host — included as a control. If this ALSO succeeds,
# you're not running where you think you are (i.e. you ran it locally).
STATS_CONTROL_URL = (
    "https://stats.nba.com/stats/scoreboardv2?GameDate=2025-01-15"
    "&LeagueID=00&DayOffset=0"
)

TIMEOUT = 15
HEADERS = {"User-Agent": "HeatCheck/1.0 (diagnostic)"}


def probe(label: str, url: str) -> tuple[bool, Any]:
    """GET a URL, reporting status, latency and payload size."""
    print(f"\n--- {label} ---")
    print(f"GET {url[:100]}")
    started = time.perf_counter()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        print(f"  TIMEOUT after {TIMEOUT}s  <- typical of an IP-level block")
        return False, None
    except requests.exceptions.RequestException as exc:
        print(f"  CONNECTION ERROR: {type(exc).__name__}: {exc}")
        return False, None

    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"  HTTP {resp.status_code} in {elapsed_ms:.0f}ms, {len(resp.content)} bytes")

    if resp.status_code != 200:
        print(f"  body preview: {resp.text[:200]}")
        return False, None

    if not resp.content:
        print("  EMPTY BODY — reachable but returned nothing")
        return False, None

    try:
        return True, resp.json()
    except json.JSONDecodeError:
        print(f"  NOT JSON. preview: {resp.text[:200]}")
        return False, None


def main() -> int:
    failures: list[str] = []

    # 1. Live scoreboard — replaces nba_api.live.scoreboard
    ok, data = probe("scoreboard (live feed source)", SCOREBOARD_URL)
    game_id = None
    if not ok:
        failures.append("scoreboard")
    else:
        games = data.get("scoreboard", {}).get("games", [])
        print(f"  parsed OK: {len(games)} games for {data['scoreboard'].get('gameDate')}")
        print(f"  feed generated at: {data.get('meta', {}).get('time')}")
        if games:
            g = games[0]
            game_id = g["gameId"]
            # Confirm the fields Phase A depends on are actually present.
            for field in ("gameId", "gameTimeUTC", "isNeutral", "gameStatus", "period"):
                print(f"    {field}: {g.get(field, '<<MISSING>>')}")
            for side in ("homeTeam", "awayTeam"):
                t = g[side]
                print(
                    f"    {side}: id={t.get('teamId')} {t.get('teamTricode')} "
                    f"score={t.get('score')} timeouts={t.get('timeoutsRemaining')}"
                )
        else:
            print("  (no games today — offseason. Shape check skipped.)")

    # 2. Box score — the Phase A payload. Only testable with a real game id.
    if game_id:
        ok, data = probe(f"boxscore for {game_id}", BOXSCORE_URL.format(game_id=game_id))
        if not ok:
            failures.append("boxscore")
            print("  NOTE: box score files only exist once a game has tipped off.")
        else:
            game = data.get("game", {})
            for side in ("homeTeam", "awayTeam"):
                players = game.get(side, {}).get("players", [])
                print(f"  {side}: {len(players)} player rows")
                if players:
                    st = players[0].get("statistics", {})
                    print(f"    sample player: {players[0].get('name')}")
                    print(f"    stat keys ({len(st)}): {sorted(st)[:12]} ...")
    else:
        print("\n--- boxscore ---\n  SKIPPED: no game id available from scoreboard.")

    # 3. Control: the host we believe is blocked.
    ok, _ = probe("stats.nba.com (CONTROL — expected to FAIL on Render)", STATS_CONTROL_URL)
    if ok:
        print("\n  !! stats.nba.com succeeded. Either you are running this locally,")
        print("     or the block no longer applies. Re-run this ON RENDER.")

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: FAILED -> {', '.join(failures)}")
        print("cdn.nba.com is not a viable free source from here. Use a paid provider.")
        return 1
    print("RESULT: OK — cdn.nba.com is reachable. Phase A can use the free feed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
