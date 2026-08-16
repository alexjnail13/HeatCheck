from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.ai.gemini import ChatUnavailableError, generate_reply

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    # Plain def: the Gemini SDK call blocks, so FastAPI threadpools this route.
    try:
        reply = generate_reply(request.message, db)
    except ChatUnavailableError:
        # Not configured (no API key). 503 says "this feature is off", which is
        # different from 502's "the upstream service misbehaved".
        raise HTTPException(
            status_code=503, detail="Ask Heat Check is not configured on this server"
        )
    except Exception:
        # Bad key, quota exhausted, network failure — all upstream problems.
        raise HTTPException(status_code=502, detail="Ask Heat Check is unavailable")
    return ChatResponse(reply=reply)
