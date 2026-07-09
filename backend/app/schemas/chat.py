"""Pydantic schemas for the 'Ask Heat Check' chat endpoint."""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """What the client sends: the user's typed message."""
    message: str


class ChatResponse(BaseModel):
    """What we send back: Gemini's reply."""
    reply: str
