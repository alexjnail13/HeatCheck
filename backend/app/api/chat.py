from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.ai.gemini import generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # Plain def: the Gemini SDK call blocks, so FastAPI threadpools this route.
    # Wrap the external call — bad key / quota / network all surface here.
    try:
        reply = generate_reply(request.message)
    except Exception:
        raise HTTPException(status_code=502, detail="Ask Heat Check is unavailable")
    return ChatResponse(reply=reply)
