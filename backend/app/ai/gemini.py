"""
Gemini client wrapper for 'Ask Heat Check'.

Phase 1: a plain chat pipe — forward the user's message to Gemini with a system
prompt that sets the assistant's persona.
Phase 2 (now): GROUNDING via context injection (Pattern A) — before each reply we
fetch live standings and paste them into the prompt so Gemini answers from real
numbers instead of stale memory.
"""
from typing import List, Optional

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from app.config import settings
from app.schemas.standings import StandingsRow
from app.services.standings import fetch_standings

MODEL = "gemini-2.5-flash"

# One client for the process, built on FIRST USE rather than at import.
#
# This used to be a module-level `genai.Client(...)`, which runs the moment
# anything imports this file. genai.Client raises on an empty API key, and
# app/main.py imports the chat router, so a missing GEMINI_API_KEY took down the
# ENTIRE app at startup: no scoreboard, no box scores, no standings. A missing
# chatbot key should only break the chatbot.
#
# Building it lazily also means a fresh clone or a CI run boots without a key.
_client: Optional[genai.Client] = None


class ChatUnavailableError(RuntimeError):
    """The chatbot can't run — usually a missing or invalid API key."""


def get_client() -> genai.Client:
    """Return the shared Gemini client, creating it the first time it's needed."""
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise ChatUnavailableError(
                "GEMINI_API_KEY is not set, so the chatbot is unavailable. "
                "The rest of the app works without it."
            )
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client

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


def generate_reply(message: str, db: Session) -> str:
    """Compute standings, inject them as context, and return Gemini's reply.

    The Gemini call blocks — this is why the route that uses it is a plain `def`
    (FastAPI runs it in a threadpool so the event loop stays free).
    """
    # Pattern A: pull data and stuff it into the prompt. Standings now come from
    # our own database. If it fails, fall back to an ungrounded reply rather than
    # erroring the whole chat.
    try:
        standings_text = _format_standings(fetch_standings(db))
        context = f"NBA standings (from our database):\n{standings_text}\n"
    except Exception:
        context = ""

    prompt = f"{context}User question: {message}"

    response = get_client().models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
        ),
    )
    return response.text
