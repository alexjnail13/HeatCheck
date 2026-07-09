import { useState, useEffect, useRef } from "react";

const WS_URL = "ws://localhost:8000/api/v1/ws/live";

/**
 * Custom hook that connects to the live game WebSocket
 * and provides real-time game updates.
 *
 * Returns: { games, isConnected }
 *   - games: array of live game state objects
 *   - isConnected: whether the WebSocket is currently connected
 */
export function useLiveGames() {
  const [games, setGames] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    // --- mount: open WebSocket connection ---
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("✅ WebSocket connected");
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const update = JSON.parse(event.data);
        setGames(update.games);
      } catch (err) {
        console.error("Failed to parse WebSocket message:", err);
      }
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };

    ws.onclose = () => {
      console.log("🔌 WebSocket disconnected");
      setIsConnected(false);
    };

    // --- unmount: close WebSocket connection ---
    return () => {
      ws.close();
    };
  }, []); // empty dependency array = runs once on mount

  return { games, isConnected };
}