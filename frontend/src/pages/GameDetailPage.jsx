import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../api/client";
import { formatGameDate } from "../utils/formatGameDate";
import { useWinProbability } from "../hooks/useWinProbability";
import WinProbabilityChart from "../components/WinProbabilityChart";
import "./GameDetailPage.css";
 
function GameDetailPage() {
  const { gameId } = useParams(); // Reads the :gameId from the URL
  const navigate = useNavigate();
 
  const [game, setGame] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Hooks must run unconditionally, before any early return (Rules of Hooks).
  const { points, loading: wpLoading, error: wpError } = useWinProbability(gameId);

  useEffect(() => {
    const fetchGame = async () => {
      try {
        const response = await api.get(`/games/${gameId}`);
        setGame(response.data);
        setLoading(false);
      } catch (err) {
        setError("Game not found.");
        setLoading(false);
      }
    };
 
    fetchGame();
  }, [gameId]);
 
  if (loading) {
    return (
      <div className="detail-page">
        <div className="loading">Loading game...</div>
      </div>
    );
  }
 
  if (error) {
    return (
      <div className="detail-page">
        <div className="error">{error}</div>
        <button className="back-btn" onClick={() => navigate("/")}>
          ← Back to games
        </button>
      </div>
    );
  }
 
  return (
    <div className="detail-page">
      <button className="back-btn" onClick={() => navigate("/")}>
        ← Back to games
      </button>
 
      <div className="game-detail-header">
        <div className="game-detail-matchup">
          <div className="detail-team">
            <span className="detail-abbr">{game.away_team_abbreviation}</span>
            <span className="detail-score">{game.away_team_score ?? "—"}</span>
          </div>
          <span className="detail-at">@</span>
          <div className="detail-team">
            <span className="detail-abbr">{game.home_team_abbreviation}</span>
            <span className="detail-score">{game.home_team_score ?? "—"}</span>
          </div>
        </div>
        <div className="game-detail-meta">
          <span>{formatGameDate(game.game_date)}</span>
          <span className="detail-status">{game.status}</span>
        </div>
      </div>
 
      <div className="win-prob-section">
        <h3>Win Probability</h3>
        {wpLoading && <p>Loading win probability…</p>}
        {wpError && <p>Couldn't load win probability.</p>}
        {!wpLoading && !wpError && points.length > 0 && (
          <WinProbabilityChart
            points={points}
            homeAbbr={game.home_team_abbreviation}
            awayAbbr={game.away_team_abbreviation}
          />
        )}
      </div>
    </div>
  );
}
 
export default GameDetailPage;