from fastapi import Depends, Header, HTTPException
from supabase import create_client

from app.config import settings

_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


def get_current_user_id(authorization: str = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    token = authorization.removeprefix("Bearer ")
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user = _client.auth.get_user(token)
        if user is None or user.user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return str(user.user.id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
