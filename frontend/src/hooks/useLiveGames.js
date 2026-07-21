import { useState, useEffect, useRef } from "react";

// Derive the WebSocket URL from the same base URL the REST client uses, so
// there's one source of truth. The scheme swap matters: http -> ws locally,
// https -> wss in production (a page served over https is not allowed to open
// an insecure ws:// socket — the browser blocks it as mixed content).
const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
const WS_URL = `${API_BASE.replace(/^http/, "ws")}/ws/live`;

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