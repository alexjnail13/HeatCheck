import { useState } from "react";
import "./BoxScore.css";

/**
 * Format a shooting percentage for display.
 *
 * The API sends null when nothing was attempted — a player who took no threes
 * did not shoot 0%. Rendering "—" preserves that distinction instead of
 * inventing a zero.
 */
function formatPct(value) {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}`;
}

/** Plus/minus is signed, and 0 is a real value distinct from "didn't play". */
function formatPlusMinus(value) {
  if (value === null || value === undefined) return "—";
  return value > 0 ? `+${value}` : `${value}`;
}

/**
 * Column definitions.
 *
 * Declared as data rather than hand-written <th>/<td> pairs so the header and
 * every row are guaranteed to stay aligned — adding a stat means adding one
 * entry, not editing two places that can drift apart.
 */
const COLUMNS = [
  { key: "minutes", label: "MIN", get: (p) => p.minutes },
  { key: "points", label: "PTS", get: (p) => p.points, emphasis: true },
  { key: "fg", label: "FG", get: (p) => `${p.fgm}-${p.fga}` },
  { key: "fg_pct", label: "FG%", get: (p) => formatPct(p.fg_pct) },
  { key: "fg3", label: "3P", get: (p) => `${p.fg3m}-${p.fg3a}` },
  { key: "fg3_pct", label: "3P%", get: (p) => formatPct(p.fg3_pct) },
  { key: "ft", label: "FT", get: (p) => `${p.ftm}-${p.fta}` },
  { key: "ft_pct", label: "FT%", get: (p) => formatPct(p.ft_pct) },
  { key: "oreb", label: "OREB", get: (p) => p.oreb },
  { key: "dreb", label: "DREB", get: (p) => p.dreb },
  { key: "rebounds", label: "REB", get: (p) => p.rebounds },
  { key: "assists", label: "AST", get: (p) => p.assists },
  { key: "steals", label: "STL", get: (p) => p.steals },
  { key: "blocks", label: "BLK", get: (p) => p.blocks },
  { key: "turnovers", label: "TO", get: (p) => p.turnovers },
  { key: "fouls", label: "PF", get: (p) => p.fouls },
  { key: "plus_minus", label: "+/-", get: (p) => formatPlusMinus(p.plus_minus) },
];

function TeamTable({ team }) {
  // Players who didn't play are separated out — a DNP row of dashes among the
  // rotation makes the table harder to scan.
  const played = team.players.filter((p) => p.played);
  const dnp = team.players.filter((p) => !p.played);

  return (
    <div className="boxscore-table-wrap">
      <table className="boxscore-table">
        <thead>
          <tr>
            <th className="col-player" scope="col">
              Player
            </th>
            {COLUMNS.map((col) => (
              <th key={col.key} scope="col">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {played.map((player) => (
            <tr key={player.player_id}>
              <th className="col-player" scope="row">
                <span className="player-name">{player.full_name}</span>
                {player.started && <span className="starter-dot" title="Starter" />}
                {player.position && (
                  <span className="player-pos">{player.position}</span>
                )}
              </th>
              {COLUMNS.map((col) => (
                <td
                  key={col.key}
                  className={col.emphasis ? "stat-emphasis" : undefined}
                >
                  {col.get(player)}
                </td>
              ))}
            </tr>
          ))}

          <tr className="totals-row">
            <th className="col-player" scope="row">
              Team totals
            </th>
            {COLUMNS.map((col) => (
              <td key={col.key} className={col.emphasis ? "stat-emphasis" : undefined}>
                {/* Team rows have no minutes or +/-, so those cells stay blank
                    rather than showing a number that doesn't mean anything. */}
                {col.key === "minutes" || col.key === "plus_minus"
                  ? ""
                  : col.get(team)}
              </td>
            ))}
          </tr>
        </tbody>
      </table>

      {dnp.length > 0 && (
        <p className="boxscore-dnp">
          <span className="dnp-label">Did not play</span>
          {dnp.map((p) => p.full_name).join(", ")}
        </p>
      )}

      {/* Only shown when we actually have the data. Games seeded from
          stats.nba.com don't break these out, and an absent number is
          better left absent than rendered as a zero. */}
      {(team.team_rebounds !== null || team.team_turnovers !== null) && (
        <p className="boxscore-team-extras">
          {team.team_rebounds !== null && (
            <span>Team rebounds: {team.team_rebounds}</span>
          )}
          {team.team_turnovers !== null && (
            <span>Team turnovers: {team.team_turnovers}</span>
          )}
        </p>
      )}
    </div>
  );
}

/**
 * Full box score with a team toggle.
 *
 * Both teams' tables exist in the DOM at once; the toggle switches which is
 * visible. That keeps scroll position per team and avoids a re-render flash
 * when switching back and forth.
 */
function BoxScore({ boxScore, loading, error }) {
  const [activeTeam, setActiveTeam] = useState("away");

  if (loading) {
    return <p className="boxscore-state">Loading box score…</p>;
  }
  if (error) {
    return <p className="boxscore-state">Couldn't load the box score.</p>;
  }
  if (!boxScore?.home && !boxScore?.away) {
    return (
      <p className="boxscore-state">
        No box score yet — this game hasn't tipped off.
      </p>
    );
  }

  const team = activeTeam === "home" ? boxScore.home : boxScore.away;
  if (!team) {
    return <p className="boxscore-state">No data for this team.</p>;
  }

  return (
    <div className="boxscore">
      <div className="boxscore-tabs" role="tablist" aria-label="Select team">
        {[
          { key: "away", data: boxScore.away },
          { key: "home", data: boxScore.home },
        ].map(({ key, data }) => (
          <button
            key={key}
            role="tab"
            aria-selected={activeTeam === key}
            className={`boxscore-tab ${activeTeam === key ? "is-active" : ""}`}
            onClick={() => setActiveTeam(key)}
            disabled={!data}
          >
            <span className="tab-abbr">{data?.abbreviation ?? "—"}</span>
            <span className="tab-score">{data?.points ?? "—"}</span>
          </button>
        ))}
      </div>

      <TeamTable team={team} />
    </div>
  );
}

export default BoxScore;
