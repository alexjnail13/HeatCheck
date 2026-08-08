import { useState, useEffect } from "react";
import api from "../api/client";

export function useWinProbability(gameId) {
  const [points, setPoints] = useState([]);
  // Which table the curve came from: "play_by_play" (~450 events, seeded after
  // the game), "snapshots" (~90 polls, while the game is live), or "none".
  // Surfaced so the UI can be honest that a live curve is coarser rather than
  // presenting both at equal authority.
  const [source, setSource] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchWinProb() {
      try {
        const response = await api.get(`/games/${gameId}/win-probability`);
        setPoints(response.data.points);
        setSource(response.data.source ?? null);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchWinProb();
  }, [gameId]);

  return { points, source, loading, error };
}
