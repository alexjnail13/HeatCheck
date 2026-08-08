"""
WebSocket client registry and the broadcast loop.

This file used to poll nba_api's scoreboard directly, compute win probability
inline, and push the result to clients without storing any of it. It now reads
from Postgres instead.

Why a polling loop is acceptable here when the old one wasn't — the loop was
never the problem, what it did was:

  * The old loop called a THIRD-PARTY api (stats.nba.com/cdn.nba.com) that
    Render's datacenter IP is blocked from, on the request path. This one reads
    our own database, which is exactly what a web service is for.
  * The old loop was the only place that data existed — nothing was persisted,
    so a client connecting at halftime had no history. Now the cron job
    (app/pipeline/ingest_live.py) owns ingestion, and this only re-reads it.
  * The old loop WROTE. Two instances meant two writers racing on the same rows.
    This one is read-only, so N instances are harmless: each serves its own
    connected clients from shared state.
  * Free-tier spin-down used to mean lost ingestion. Now it means no connected
    clients — which is the only time it's safe to stop broadcasting anyway.

Win probability is computed on every pass from stored raw state, never cached,
so retraining the model updates every client on the next tick.
"""

import asyncio
import logging

from app.database.session import SessionLocal
from app.schemas.live import LiveUpdate
from app.services.live_state import build_live_update

logger = logging.getLogger(__name__)

# How often to re-read Postgres and push to clients. Independent of the cron
# cadence that fills the table — this only controls how quickly a client sees
# what's already stored.
BROADCAST_INTERVAL = 10

# Skip the database round trip entirely when nobody is listening.
IDLE_INTERVAL = 30


# ---------- connected WebSocket clients ----------
_connected_clients: set = set()


def register_client(websocket) -> None:
    """Add a WebSocket client to receive live updates."""
    _connected_clients.add(websocket)


def unregister_client(websocket) -> None:
    """Remove a WebSocket client."""
    _connected_clients.discard(websocket)


def client_count() -> int:
    return len(_connected_clients)


def read_live_update() -> LiveUpdate | None:
    """Read current live state from Postgres. Returns None on failure."""
    db = SessionLocal()
    try:
        return build_live_update(db)
    except Exception as exc:
        # A database blip must not kill the loop — log and try again next tick.
        logger.error("Failed to build live update: %s", exc)
        return None
    finally:
        db.close()


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

    for client in disconnected:
        _connected_clients.discard(client)


async def send_snapshot_to(websocket) -> None:
    """
    Push current state to one client immediately on connect.

    Without this a client waits up to BROADCAST_INTERVAL seconds staring at an
    empty page. It's also the fix for the halftime case: the first message
    carries the full current state, not just what changed since connecting.
    """
    loop = asyncio.get_event_loop()
    update = await loop.run_in_executor(None, read_live_update)
    if update is not None:
        try:
            await websocket.send_text(update.model_dump_json())
        except Exception as exc:
            logger.warning("Failed to send initial snapshot: %s", exc)


async def start_broadcast_loop() -> None:
    """
    Re-read Postgres on a timer and push to connected clients. Runs forever.

    The database read is synchronous (SQLAlchemy), so it runs in a thread pool
    to avoid blocking the event loop and stalling every other request.
    """
    logger.info("Live broadcast loop started (reading from Postgres).")

    while True:
        if not _connected_clients:
            await asyncio.sleep(IDLE_INTERVAL)
            continue

        loop = asyncio.get_event_loop()
        update = await loop.run_in_executor(None, read_live_update)

        if update is not None:
            await broadcast(update)

        await asyncio.sleep(BROADCAST_INTERVAL)
