// Decide a row's playoff tier from its conference seed.
// 1-6 clinch a playoff spot, 7-10 are the play-in tournament, 11-15 are out.
function seedTier(seed) {
  if (seed <= 6) return "playoff";
  if (seed <= 10) return "playin";
  return "eliminated";
}

function ConferenceTable({ title, rows }) {
  return (
    <div className="conf-table">
      <h2 className="conf-title">{title}</h2>
      <table className="standings-table">
        <thead>
          <tr>
            <th className="col-seed">#</th>
            <th className="col-team">Team</th>
            <th>W</th>
            <th>L</th>
            <th>PCT</th>
            <th>GB</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.team_name} className={`tier-${seedTier(row.seed)}`}>
              <td className="col-seed">{row.seed}</td>
              <td className="col-team">{row.team_name}</td>
              <td>{row.wins}</td>
              <td>{row.losses}</td>
              <td>{row.win_pct.toFixed(3).replace(/^0/, "")}</td>
              <td>{row.games_behind === 0 ? "—" : row.games_behind}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ConferenceTable;
