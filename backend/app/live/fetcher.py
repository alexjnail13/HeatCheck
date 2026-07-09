"""
Live game data fetcher.

Polls nba_api's live scoreboard on a timer, extracts game state,
computes ML features, and runs win probability predictions.
"""

import asyncio
import re
import logging
from datetime import datetime, timezone

from nba_api.live.nba.endpoints import scoreboard

from app.ml.inference import predict_win_probability
from app.schemas.live import LiveGameState, LiveUpdate

logger = logging.getLogger(__name__)

# How often to poll nba_api (seconds)
POLL_INTERVAL = 30


def parse_clock_to_seconds(clock: str) -> float:
    """
    Parse a game clock string into seconds remaining in the period.
    Handles two formats:
      - ISO 8601: "PT04M30.00S" (letters present)
      - Simple:   "4:30" or "4:30.0"

    Returns:
        Seconds remaining in the current period.
    """
    if not clock or clock.strip() == "":
        return 0.0

    # ISO 8601 format: "PT04M30.00S"
    if "PT" in clock.upper():
        match = re.match(
            r"PT(\d+)M([\d.]+)S",
            clock.strip(),
            re.IGNORECASE,
        )
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            return minutes * 60 + seconds
        return 0.0

    # Simple format: "4:30" or "4:30.0"
    parts = clock.strip().split(":")
    if len(parts) == 2:
        try:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        except ValueError:
            return 0.0

    return 0.0


def compute_time_remaining(period: int, clock: str) -> float:
    """
    Compute total seconds remaining in the game.

    Formula: (4 - period) * 720 + period_seconds
    For overtime: period > 4, each OT is 5 minutes (300 seconds).

    Args:
        period: Current period (1-4 regular, 5+ overtime).
        clock: Clock string for current period.

    Returns:
        Total seconds remaining in the game.
    """
    period_seconds = parse_clock_to_seconds(clock)

    if period <= 4:
        # Regular time: remaining full quarters + current period clock
        return (4 - period) * 720 + period_seconds
    else:
        # Overtime: only current OT period remaining
        return period_seconds


def compute_win_pct(wins: int, losses: int) -> float:
    """Compute win percentage, handling zero games played."""
    total = wins + losses
    if total == 0:
        return 0.5  # assume average if no games played
    return wins / total


def parse_game(game: dict) -> LiveGameState | None:
    """
    Parse a single game from the scoreboard response into a LiveGameState.

    Only runs the ML model for in-progress games (gameStatus == 2).
    Not-started and final games get a default probability.

    Args:
        game: Raw game dict from nba_api scoreboard.

    Returns:
        LiveGameState or None if parsing fails.
    """
    try:
        game_id = game["gameId"]
        game_status = game["gameStatus"]
        game_status_text = game.get("gameStatusText", "")
        period = game.get("period", 0)
        clock = game.get("gameClock", "")

        home = game["homeTeam"]
        away = game["awayTeam"]

        home_score = home.get("score", 0)
        away_score = away.get("score", 0)

        # Compute time remaining
        time_remaining = compute_time_remaining(period, clock)

        # Compute win probability
        if game_status == 2:
            # Game is live — run the ML model
            point_differential = home_score - away_score
            home_win_pct = compute_win_pct(home["wins"], home["losses"])
            away_win_pct = compute_win_pct(away["wins"], away["losses"])
            team_strength_diff = home_win_pct - away_win_pct

            home_win_prob = predict_win_probability(
                point_differential=point_differential,
                time_remaining_seconds=time_remaining,
                team_strength_diff=team_strength_diff,
            )
        elif game_status == 3:
            # Game is final — whoever has more points won
            home_win_prob = 1.0 if home_score > away_score else 0.0
        else:
            # Game hasn't started — use team strength as baseline
            home_win_pct = compute_win_pct(home["wins"], home["losses"])
            away_win_pct = compute_win_pct(away["wins"], away["losses"])
            home_win_prob = 0.5 + (home_win_pct - away_win_pct) / 2

        return LiveGameState(
            game_id=game_id,
            game_status=game_status,
            game_status_text=game_status_text,
            period=period,
            clock=clock,
            time_remaining_seconds=time_remaining,
            home_team_id=home["teamId"],
            home_team_tricode=home["teamTricode"],
            home_team_score=home_score,
            away_team_id=away["teamId"],
            away_team_tricode=away["teamTricode"],
            away_team_score=away_score,
            home_win_probability=home_win_prob,
        )

    except Exception as e:
        logger.error(f"Error parsing game: {e}")
        return None


async def fetch_live_scoreboard() -> LiveUpdate | None:
    """
    Fetch today's scoreboard from nba_api and parse all games.

    Runs the blocking nba_api call in a thread pool to avoid
    blocking the async event loop.

    Returns:
        LiveUpdate with all games, or None if fetch fails.
    """
    try:
        # nba_api is synchronous — run in thread pool so we don't block
        loop = asyncio.get_event_loop()
        sb = await loop.run_in_executor(None, scoreboard.ScoreBoard)
        raw = sb.get_dict()

        games_data = raw.get("scoreboard", {}).get("games", [])

        live_games = []
        for game in games_data:
            parsed = parse_game(game)
            if parsed:
                live_games.append(parsed)

        return LiveUpdate(
            games=live_games,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.error(f"Error fetching scoreboard: {e}")
        return None


# ---------- store for connected WebSocket clients ----------
_connected_clients: set = set()


def register_client(websocket) -> None:
    """Add a WebSocket client to receive live updates."""
    _connected_clients.add(websocket)


def unregister_client(websocket) -> None:
    """Remove a WebSocket client."""
    _connected_clients.discard(websocket)


async def broadcast(update: LiveUpdate) -> None:
    """Send a live update to all connected WebSocket clients."""
    if not _connected_clients:
        return

    message = update.model_dump_json()
    disconnected = set()

    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)

    # Clean up dead connections
    for client in disconnected:
        _connected_clients.discard(client)


async def start_polling_loop() -> None:
    """
    Main polling loop. Runs forever in the background.
    Fetches scoreboard → parses games → runs predictions → broadcasts to clients.
    """
    logger.info("🏀 Live game polling loop started.")

    while True:
        update = await fetch_live_scoreboard()

        if update and update.games:
            logger.info(
                f"📡 Broadcasting {len(update.games)} games to "
                f"{len(_connected_clients)} clients."
            )
            await broadcast(update)

        await asyncio.sleep(POLL_INTERVAL)