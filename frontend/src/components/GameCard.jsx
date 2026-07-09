import { useNavigate } from "react-router-dom";
import "./GameCard.css";

function GameCard({ game }) {
  const navigate = useNavigate();

  const handleClick = () => {
    navigate(`/games/${game.id}`);
  };

  return (
    <div
      className={`game-card ${game.isLive ? "live" : ""}`}
      onClick={handleClick}
    >
      <div className="game-card-top">{game.topText}</div>
      <div className="game-card-matchup">
        <div className="game-card-team">
          <span className="team-abbr">{game.awayAbbr}</span>
          <span className="team-score">{game.awayScore ?? "—"}</span>
        </div>
        <span className="game-card-at">@</span>
        <div className="game-card-team">
          <span className="team-abbr">{game.homeAbbr}</span>
          <span className="team-score">{game.homeScore ?? "—"}</span>
        </div>
      </div>
      <div className={`game-card-status ${game.isLive ? "live" : ""}`}>
        {game.statusText}
      </div>
    </div>
  );
}

export default GameCard;
