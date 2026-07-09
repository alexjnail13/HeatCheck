import { useState, useEffect } from "react";
import client from "../api/client";

export function useStandings() {
  const [standings, setStandings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchStandings() {
      try {
        const response = await client.get("/standings");
        setStandings(response.data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchStandings();
  }, []);

  return { standings, loading, error };
}
