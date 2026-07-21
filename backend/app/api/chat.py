from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.ai.gemini import generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    # Plain def: the Gemini SDK call blocks, so FastAPI threadpools this route.
    # Wrap the external call — bad key / quota / network all surface here.
    try:
        reply = generate_reply(request.message, db)
    except Exception:
        raise HTTPException(status_code=502, detail="Ask Heat Check is unavailable")
    return ChatResponse(reply=reply)
