"""
Gemini client wrapper for 'Ask Heat Check'.

Phase 1: a plain chat pipe — forward the user's message to Gemini with a system
prompt that sets the assistant's persona.
Phase 2 (now): GROUNDING via context injection (Pattern A) — before each reply we
fetch live standings and paste them into the prompt so Gemini answers from real
numbers instead of stale memory.
"""
from typing import List

from google import genai
from google.genai import types

from app.config import settings
from app.schemas.standings import StandingsRow
from app.services.standings import fetch_standings

# One client for the process. Reads the key from settings (-> .env).
_client = genai.Client(api_key=settings.GEMINI_API_KEY)

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are \"Ask Heat Check\", the AI assistant inside Heat Check, a real-time "
    "NBA analytics app for fans and sports bettors. You help users understand NBA "
    "stats, standings, matchups, and win-probability insights. Be concise, sharp, "
    "and conversational. When live standings are provided below, ALWAYS use them as "
    "the source of truth and never invent numbers. If a question needs live data "
    "that is NOT provided (e.g. tonight's scores), say so plainly instead of guessing."
)


def _format_standings(rows: List[StandingsRow]) -> str:
    """Render standings as compact text for the prompt, grouped and seed-sorted."""
    lines: List[str] = []
    for conf_name, conf_key in [("Eastern", "East"), ("Western", "West")]:
        teams = sorted(
            (r for r in rows if r.conference == conf_key), key=lambda r: r.seed
        )
        lines.append(f"{conf_name} Conference:")
        for r in teams:
            lines.append(
                f"  {r.seed}. {r.team_name} "
                f"({r.wins}-{r.losses}, {r.win_pct:.3f} win%, {r.games_behind} GB)"
            )
        lines.append("")
    return "\n".join(lines)


def generate_reply(message: str) -> str:
    """Fetch live standings, inject them as context, and return Gemini's reply.

    Blocking network calls (nba_api + Gemini) — this is why the route that uses it
    is a plain `def` (FastAPI runs it in a threadpool so the event loop stays free).
    """
    # Pattern A: pull live data and stuff it into the prompt. If the fetch fails,
    # fall back to an ungrounded reply rather than erroring the whole chat.
    try:
        standings_text = _format_standings(fetch_standings())
        context = f"Live NBA standings (current):\n{standings_text}\n"
    except Exception:
        context = ""

    prompt = f"{context}User question: {message}"

    response = _client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
        ),
    )
    return response.text
