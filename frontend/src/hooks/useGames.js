import { useState, useEffect } from "react";
import client from "../api/client";  

export function useGames() {
  // three pieces of state — you named these
  const [restGames, setRestGames] = useState([]);  
  const [loading, setLoading]     = useState(true);   
  const [error, setError]         = useState(null);   
  useEffect(() => {
    
    async function fetchGames() {
      try {
        const response = await client.get("/games");   
        setRestGames(response.data);
      } catch (err) {
        setError(err.message);            
      } finally {
        setLoading(false);          
      }
    }

    fetchGames();
  }, []);                       

  return { restGames, loading, error }; 
}