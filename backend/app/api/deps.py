"""Reusable FastAPI dependencies for authentication."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import User
from app.core.security import decode_access_token

# auto_error=False -> we raise our own uniform 401 (even for a missing header),
# instead of HTTPBearer's default 403.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Turn an `Authorization: Bearer <jwt>` header into the current User.

    Raises 401 if the token is missing/invalid/expired, or if it decodes to a
    user that no longer exists.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Failure point 1: no header, or bad/expired token
    if credentials is None:
        raise credentials_exception

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise credentials_exception

    # Failure point 2: valid token, but no such user in the DB
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
    except ValueError:
        raise credentials_exception

    if user is None:
        raise credentials_exception

    return user
