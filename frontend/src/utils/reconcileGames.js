export function reconcileGames(liveGames, restGames) {
  const liveIds = new Set(liveGames.map((g) => g.game_id));

  const live = liveGames;

  const upcoming = restGames.filter(
    (g) => g.status === "Scheduled" && !liveIds.has(g.nba_game_id)
  );

  const completed = restGames.filter(
    (g) => g.status === "Final" && !liveIds.has(g.nba_game_id)
  );

  return { live, upcoming, completed };
}