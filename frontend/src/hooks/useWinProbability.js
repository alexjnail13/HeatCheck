import { useState, useEffect } from "react";
import api from "../api/client";

export function useWinProbability(gameId) {
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchWinProb() {
      try {
        const response = await api.get(`/games/${gameId}/win-probability`);
        setPoints(response.data.points);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchWinProb();
  }, [gameId]);

  return { points, loading, error };
}
