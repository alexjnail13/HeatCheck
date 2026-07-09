import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

const REGULATION_SECONDS = 2880; // 48 min × 60

function WinProbabilityChart({ points, homeAbbr, awayAbbr }) {
  // Transform each API point into what the chart plots.
  // x = elapsed game time (counts UP), y = home win % (0–100).
  const data = points.map((p) => ({
    elapsed: REGULATION_SECONDS - p.time_remaining_seconds,
    homeWinPct: Math.round(p.home_win_probability * 100),
    homeScore: p.home_score,
    awayScore: p.away_score,
  }));

  return (
    <div style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2532" />
          <XAxis
            dataKey="elapsed"
            type="number"
            domain={[0, REGULATION_SECONDS]}
            tickFormatter={(s) => `Q${Math.min(4, Math.floor(s / 720) + 1)}`}
            ticks={[0, 720, 1440, 2160, 2880]}
            stroke="#6b7a90"
          />
          <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} stroke="#6b7a90" />
          <ReferenceLine y={50} stroke="#6b7a90" strokeDasharray="4 4" />
          <Tooltip
            formatter={(value) => [`${value}%`, `${homeAbbr} win prob`]}
            labelFormatter={() => ""}
            contentStyle={{
              background: "#151921",
              border: "1px solid #1e2532",
              borderRadius: 8,
            }}
          />
          <Line
            type="monotone"
            dataKey="homeWinPct"
            stroke="#f97316"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default WinProbabilityChart;
