import { useLiveGames } from "../hooks/useLiveGames";
import { useGames } from "../hooks/useGames";
import { reconcileGames } from "../utils/reconcileGames";
import { normalizeLiveGame, normalizeRestGame } from "../utils/normalizeGame";
import GameCard from "../components/GameCard";
import "./HomePage.css";

export default function HomePage() {
  const { games: liveGames, isConnected } = useLiveGames();
  const { restGames, loading, error } = useGames();

  // Merge the two sources into three deduplicated lists
  const { live, upcoming, completed } = reconcileGames(liveGames, restGames);

  // Normalize each list into the canonical shape GameCard expects
  const liveCards = live.map(normalizeLiveGame);
  const upcomingCards = upcoming.map(normalizeRestGame);
  const completedCards = completed.map(normalizeRestGame);

  if (loading) return <p className="home-state">Loading games…</p>;
  if (error) return <p className="home-state">Error trying to load games.</p>;

  return (
    <div className="home">
      <div className={`conn-status ${isConnected ? "online" : "offline"}`}>
  <span className="conn-dot" />
  {isConnected ? "Live" : "Reconnecting…"}
</div>
      {liveCards.length > 0 && (
        <section className="game-section">
          <div className="section-header live">
            <h2 className="section-title">Live</h2>
            <span className="section-count">{liveCards.length}</span>
          </div>
          <div className="game-grid">
            {liveCards.map((g) => (
              <GameCard key={g.id} game={g} />
            ))}
          </div>
        </section>
      )}

      {upcomingCards.length > 0 && (
        <section className="game-section">
          <div className="section-header">
            <h2 className="section-title">Upcoming</h2>
            <span className="section-count">{upcomingCards.length}</span>
          </div>
          <div className="game-grid">
            {upcomingCards.map((g) => (
              <GameCard key={g.id} game={g} />
            ))}
          </div>
        </section>
      )}

      {completedCards.length > 0 && (
        <section className="game-section">
          <div className="section-header">
            <h2 className="section-title">Completed</h2>
            <span className="section-count">{completedCards.length}</span>
          </div>
          <div className="game-grid">
            {completedCards.map((g) => (
              <GameCard key={g.id} game={g} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}