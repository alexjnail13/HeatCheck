import { useState, useEffect, useCallback, useRef } from "react";
import api from "../api/client";

/**
 * Fetch a game's box score.
 *
 * While a game is live the box score keeps changing, so this re-fetches on an
 * interval — but only when the API says the game is actually live. A finished
 * game is fetched once and left alone; polling it forever would be pure waste,
 * since those rows never change again.
 *
 * The interval matches the ingestion cron's cadence. Polling faster than the
 * data is written just re-reads the same rows.
 *
 * @param {string} gameId  NBA game id (e.g. "0042500222")
 * @param {number} pollMs  How often to re-fetch while live. Default 60s.
 */
export function useBoxScore(gameId, pollMs = 60000) {
  const [boxScore, setBoxScore] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  const fetchBoxScore = useCallback(async () => {
    try {
      const response = await api.get(`/games/${gameId}/boxscore`);
      setBoxScore(response.data);
      setError(null);
      return response.data;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [gameId]);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      const data = await fetchBoxScore();
      if (cancelled) return;

      // Only schedule another fetch if the game is still going.
      if (data?.is_live) {
        timerRef.current = setTimeout(tick, pollMs);
      }
    };

    setLoading(true);
    tick();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchBoxScore, pollMs]);

  return { boxScore, loading, error, refetch: fetchBoxScore };
}
