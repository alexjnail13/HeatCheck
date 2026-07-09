"""
WebSocket endpoint for live game updates.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.live.fetcher import register_client, unregister_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/live")
async def live_game_updates(websocket: WebSocket):
    """
    WebSocket endpoint for receiving live game updates.

    Flow:
    1. Client connects
    2. Server accepts the connection
    3. Client is registered to receive broadcasts from the polling loop
    4. Connection stays open until the client disconnects
    """
    await websocket.accept()
    register_client(websocket)
    logger.info("🔌 Client connected to live updates.")

    try:
        # Keep the connection alive — wait for client messages
        # (we don't expect any, but this keeps the connection open)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("🔌 Client disconnected from live updates.")
    finally:
        unregister_client(websocket)