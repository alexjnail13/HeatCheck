"""
Standings business logic — the single source of truth for fetching NBA standings.

Both the /standings API route and the 'Ask Heat Check' chatbot import this, so
the nba_api fetch + mapping lives in exactly one place (no duplicate logic to
drift apart). This function raises on failure; each caller decides how to handle
it (the route -> HTTP 503, the chatbot -> fall back to ungrounded).
"""
from typing import List

from nba_api.stats.endpoints import leaguestandingsv3

from app.schemas.standings import StandingsRow


def fetch_standings(season: str = "2025-26") -> List[StandingsRow]:
    standings = leaguestandingsv3.LeagueStandingsV3(season=season)
    df = standings.get_data_frames()[0]

    rows: List[StandingsRow] = []
    for _, team in df.iterrows():
        rows.append(
            StandingsRow(
                team_name=team["TeamCity"] + " " + team["TeamName"],
                conference=team["Conference"],
                seed=int(team["PlayoffRank"]),
                wins=int(team["WINS"]),
                losses=int(team["LOSSES"]),
                win_pct=float(team["WinPCT"]),
                games_behind=float(team["ConferenceGamesBack"]),
            )
        )
    return rows
