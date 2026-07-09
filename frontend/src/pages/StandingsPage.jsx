import { useStandings } from "../hooks/useStandings";
import ConferenceTable from "../components/ConferenceTable";
import "./StandingsPage.css";

function StandingsPage() {
  const { standings, loading, error } = useStandings();

  if (loading) {
    return (
      <div className="standings-page">
        <div className="loading">Loading standings…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="standings-page">
        <div className="error">Couldn't load standings.</div>
      </div>
    );
  }

  // Transform: one flat array -> two seed-sorted conference lists.
  const east = standings
    .filter((row) => row.conference === "East")
    .sort((a, b) => a.seed - b.seed);
  const west = standings
    .filter((row) => row.conference === "West")
    .sort((a, b) => a.seed - b.seed);

  return (
    <div className="standings-page">
      <header className="page-header">
        <h1>Standings</h1>
        <p className="page-subtitle">Playoff &amp; play-in picture</p>
      </header>

      <div className="standings-grid">
        <ConferenceTable title="Eastern Conference" rows={east} />
        <ConferenceTable title="Western Conference" rows={west} />
      </div>
    </div>
  );
}

export default StandingsPage;
