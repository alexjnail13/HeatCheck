import { formatGameDate } from "./formatGameDate";

// Live games arrive shaped like LiveGameState (from the WebSocket)
export function normalizeLiveGame(game) {
  return {
    id: game.game_id,
    awayAbbr: game.away_team_tricode,
    homeAbbr: game.home_team_tricode,
    awayScore: game.away_team_score,
    homeScore: game.home_team_score,
    statusText: game.game_status_text,
    topText: game.game_status_text,
    isLive: true,
  };
}

// REST games arrive shaped like GameResponse (from GET /games)
export function normalizeRestGame(game) {
  return {
    id: game.nba_game_id,
    awayAbbr: game.away_team_abbreviation,
    homeAbbr: game.home_team_abbreviation,
    awayScore: game.away_team_score,
    homeScore: game.home_team_score,
    statusText: game.status,
    topText: formatGameDate(game.game_date),
    isLive: false,
  };
}